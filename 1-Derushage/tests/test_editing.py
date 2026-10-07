import copy,json,sys,tempfile,unittest,threading,subprocess
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import core,editing

class EditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.original=core.PROJECTS;core.PROJECTS=Path(self.tmp.name)
        self.job='test-project'
        sources=[dict(name='A.mp4',duration=4,fps='25',width=160,height=90),dict(name='B.mp4',duration=3,fps='25',width=160,height=90)]
        t=core.make_timeline([dict(s,silences=[[1,3]] if i==0 else []) for i,s in enumerate(sources)],core.DEFAULTS)
        core.save_json(core.PROJECTS/self.job/'decoupage.json',t)
        self.doc=editing.initialize(self.job)
    def tearDown(self):core.PROJECTS=self.original;self.tmp.cleanup()
    def test_restore_and_change_cut_preserve_sources(self):
        before=editing.build_timeline(self.doc)['planned_output_seconds']
        clips=copy.deepcopy(self.doc['clips']);clips[0]['cuts'][0]['decision']='rejected'
        result=editing.save(self.job,dict(revision=1,clips=clips))
        self.assertGreater(result['duration_frames']/25,before);self.assertEqual(result['duration_frames'],175)
        restored=editing.read(self.job);self.assertEqual(restored['sources'],self.doc['sources']);self.assertEqual(restored['clips'],clips)
        self.assertTrue((core.PROJECTS/self.job/'versions'/'montage-v0001.json').exists())
    def test_pending_keeps_pause_and_prevents_approval(self):
        clips=copy.deepcopy(self.doc['clips']);clips[0]['cuts'][0]['decision']='pending'
        result=editing.save(self.job,dict(revision=1,clips=clips))
        self.assertEqual(result['duration_frames'],175)
        with self.assertRaises(ValueError):editing.approve(self.job,2)
    def test_invalid_ranges_duplicates_and_unknown_sources(self):
        for edit in [lambda c:c[0].update(start=70,end=20),lambda c:c[0].update(end=101),lambda c:c[0].update(start=float('nan')),lambda c:c[0]['cuts'][0].update(end=101),lambda c:c.__setitem__(1,copy.deepcopy(c[0]))]:
            clips=copy.deepcopy(self.doc['clips']);edit(clips)
            with self.assertRaises(ValueError):editing.save(self.job,dict(revision=1,clips=clips))
        clips=copy.deepcopy(self.doc['clips']);clips[0]['source_index']=999
        result=editing.save(self.job,dict(revision=1,clips=clips));self.assertEqual(result['clips'][0]['source_index'],0)
    def test_stale_save_and_approval_invalidated(self):
        editing.approve(self.job,1);snapshot=editing.approved_snapshot(self.job,1,'preview')
        clips=copy.deepcopy(self.doc['clips']);clips.reverse()
        result=editing.save(self.job,dict(revision=1,clips=clips));self.assertIsNone(result['approved_revision'])
        with self.assertRaises(editing.Conflict):editing.save(self.job,dict(revision=1,clips=clips))
        with self.assertRaises(editing.Conflict):editing.approved_snapshot(self.job,1,'preview')
        self.assertEqual(snapshot['parent_revision'],1);self.assertEqual(snapshot['segments'][0]['source'],'A.mp4')
        self.assertEqual(editing.build_timeline(editing.read(self.job))['segments'][0]['source'],'B.mp4')
    def test_edit_does_not_start_analysis_or_render(self):
        with patch.object(core,'render') as render,patch.object(core,'detect_silences') as detect,patch.object(core,'n8n_request') as network:
            clips=copy.deepcopy(self.doc['clips']);clips[0]['start']=5
            editing.save(self.job,dict(revision=1,clips=clips))
            render.assert_not_called();detect.assert_not_called();network.assert_not_called()
    def test_approval_notification_uses_immutable_version(self):
        editing.approve(self.job,1)
        clips=copy.deepcopy(self.doc['clips']);clips.reverse();editing.save(self.job,dict(revision=1,clips=clips))
        with patch.object(core,'n8n_request',return_value={'ok':True}) as network:
            editing.notify_approval(self.job,1)
        self.assertEqual(network.call_args.args[0]['summary']['revision'],1)
        self.assertIsNone(editing.read(self.job)['approved_revision'])

@unittest.skipUnless(core.FFMPEG.is_file() and core.FFPROBE.is_file(), 'FFmpeg/FFprobe nécessaires au test de rendu')
class ExportOrderTest(unittest.TestCase):
    def test_export_order_blue_red_blue_and_exact_duration(self):
        oldwork,oldprojects=core.WORK,core.PROJECTS
        try:
            core.WORK=ROOT/'.work'/'editor-render-check';core.PROJECTS=core.WORK/'projects'
            sources=[]
            for name in ['01.mp4','02.mp4']:
                path=ROOT/'.work'/'synthetic-check'/'sources'/name
                path.parent.mkdir(parents=True,exist_ok=True)
                color='red' if name=='01.mp4' else 'blue'
                core.run_ffmpeg(['-y','-f','lavfi','-i',f'color=c={color}:s=160x90:r=25:d=3',
                                 '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=3',
                                 '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',path],path.with_suffix('.log'))
                info=core.probe(path);info['fingerprint']=core.fingerprint(path);sources.append(info)
            intervals=[(1,.4,1.4),(0,.4,1.4),(1,1.4,1.8)]
            t=dict(parameters=dict(core.DEFAULTS,quality='full'),sources=sources,fps='25',planned_output_seconds=2.4,segments=[])
            at=0
            for i,a,b in intervals:
                frames=round((b-a)*25);t['segments'].append(dict(source_index=i,source=sources[i]['name'],source_start=a,source_end=b,frames=frames,output_start=at,output_end=at+frames/25));at+=frames/25
            (core.PROJECTS/'order').mkdir(parents=True,exist_ok=True)
            output,info=core.render(t,'order',lambda *a:None,threading.Event());self.assertAlmostEqual(info['duration'],2.4,delta=.04)
            for timestamp,channel in [('0.2',2),('1.2',0),('2.2',2)]:
                r=subprocess.run([str(core.FFMPEG),'-v','error','-ss',timestamp,'-i',str(output),'-frames:v','1','-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,check=True,creationflags=core.CREATE_FLAGS)
                self.assertGreater(r.stdout[channel],150)
        finally:core.WORK,core.PROJECTS=oldwork,oldprojects

if __name__=='__main__':unittest.main(verbosity=2)
