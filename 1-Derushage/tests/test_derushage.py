import copy
import importlib.util
import json
import math
import subprocess
import threading
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('core', ROOT/'core.py')
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

def source(name,duration,silences):
    return dict(name=name,duration=duration,silences=silences,fps='50',width=160,height=90)

class TimelineTests(unittest.TestCase):
    def test_short_pause_untouched(self):
        t=core.make_timeline([source('a.mp4',4,[[1,1.5]])],core.DEFAULTS)
        self.assertEqual(t['cuts'],[])
        self.assertEqual(t['planned_output_seconds'],4)

    def test_long_pause_keeps_safety_margin(self):
        t=core.make_timeline([source('a.mp4',4,[[1,3]])],core.DEFAULTS)
        self.assertEqual(len(t['cuts']),1)
        self.assertGreaterEqual(t['cuts'][0]['start'],1.15)
        self.assertLessEqual(t['cuts'][0]['end'],2.85)
        self.assertAlmostEqual(t['planned_output_seconds'],2.32)

    def test_pause_across_two_files(self):
        t=core.make_timeline([source('a.mp4',2,[[1.4,2]]),source('b.mp4',2,[[0,.5]])],core.DEFAULTS)
        self.assertEqual(len(t['cuts']),1)
        self.assertAlmostEqual(t['segments'][0]['source_end'],1.56)
        self.assertAlmostEqual(t['segments'][1]['source_start'],.34)
        self.assertAlmostEqual(t['segments'][0]['output_end'],t['segments'][1]['output_start'])

    def test_assemble_mode_has_no_cuts(self):
        t=core.make_timeline([source('a.mp4',4,[[0,2]])],dict(core.DEFAULTS,mode='assemble'))
        self.assertEqual(t['cuts'],[])
        self.assertEqual(t['planned_output_seconds'],4)

    def test_outer_edges_can_be_preserved(self):
        t=core.make_timeline([source('a.mp4',5,[[0,2],[3,5]])],dict(core.DEFAULTS,trim_edges=False))
        self.assertEqual(t['cuts'],[])

    def test_all_silence_is_not_exported_as_a_false_success(self):
        with self.assertRaises(ValueError):
            core.make_timeline([source('a.mp4',4,[[0,4]])],core.DEFAULTS)

    def test_bad_parameters_rejected(self):
        for params in [dict(core.DEFAULTS,keep_pause=1,min_pause=.5),dict(core.DEFAULTS,threshold_db=math.nan),dict(core.DEFAULTS,min_pause=True)]:
            with self.assertRaises(ValueError):
                core.validate_parameters(params)

@unittest.skipUnless(core.FFMPEG.is_file() and core.FFPROBE.is_file(), 'FFmpeg/FFprobe nécessaires au test de rendu')
class RenderTests(unittest.TestCase):
    def test_synthetic_cut_keeps_audio_and_image_synchronized(self):
        oldwork,oldprojects=core.WORK,core.PROJECTS
        try:
            core.WORK=ROOT/'.work'/'synthetic-check'
            core.PROJECTS=core.WORK/'results'
            fixture=core.WORK/'sources';fixture.mkdir(parents=True,exist_ok=True)
            sources=[]
            for name,color,expr in [('01.mp4','red','if(lt(t,1),0.4*sin(2*PI*440*t),0)'),('02.mp4','blue','if(gt(t,1),0.4*sin(2*PI*880*t),0)')]:
                path=fixture/name
                core.run_ffmpeg(['-y','-f','lavfi','-i',f'color=c={color}:s=160x90:r=25:d=3',
                                 '-f','lavfi','-i',f"aevalsrc=exprs='{expr}':s=48000:d=3",'-c:v','libx264',
                                 '-pix_fmt','yuv420p','-c:a','aac','-shortest',path],fixture/(name+'.log'))
                info=core.probe(path);info['fingerprint']=core.fingerprint(path)
                info['silences']=core.detect_silences(info,-35)
                sources.append(info)
            t=core.make_timeline(sources,dict(core.DEFAULTS,quality='full'))
            (core.PROJECTS/'test').mkdir(parents=True,exist_ok=True)
            output,info=core.render(t,'test',lambda *args:None,threading.Event())
            self.assertAlmostEqual(info['duration'],3.32,delta=.05)
            out=core.probe(output);out['fingerprint']=core.fingerprint(output)
            silences=core.detect_silences(out,-35)
            pause=next(x for x in silences if x[0]<1.05 and x[1]>1.25)
            self.assertAlmostEqual(pause[0],1,delta=.035)
            self.assertAlmostEqual(pause[1],1.32,delta=.04)
            for timestamp,channel in [('1.10',0),('1.22',2)]:
                r=subprocess.run([str(core.FFMPEG),'-v','error','-ss',timestamp,'-i',str(output),'-frames:v','1',
                                  '-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,
                                 creationflags=core.CREATE_FLAGS,timeout=30,check=True)
                self.assertGreater(r.stdout[channel],150)
                self.assertLess(r.stdout[2 if channel==0 else 0],50)
            (core.WORK/'verification.json').write_text(json.dumps({'duration':info['duration'],'pause':pause,'red_then_blue':True}),encoding='utf-8')
        finally:
            core.WORK,core.PROJECTS=oldwork,oldprojects

if __name__=='__main__':
    unittest.main(verbosity=2)
