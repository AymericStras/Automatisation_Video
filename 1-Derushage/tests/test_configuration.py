import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import core

class ConfigurationTests(unittest.TestCase):
    def test_instance_can_change(self):
        for host in ['studio.example','autre.app.n8n.cloud']:
            endpoint=f'https://{host}/webhook/derushage-test'
            self.assertEqual(core.validate_n8n_endpoint({'n8n_webhook':endpoint,'workflow_url':f'https://{host}/workflow/demo'}),endpoint)

    def test_wrong_urls_are_rejected_before_network_call(self):
        for endpoint in ['https://studio.example/assistant/demo',
                         'https://studio.example/mcp-server/http',
                         'https://studio.example/webhook-test/demo',
                         'http://studio.example/webhook/demo',
                         'https://elsewhere.example/webhook/demo',
                         'https://user:password@studio.example/webhook/demo',
                         'https://studio.example/webhook/',None]:
            with self.subTest(endpoint=endpoint),self.assertRaises(ValueError):
                core.validate_n8n_endpoint({'n8n_webhook':endpoint,'workflow_url':'https://studio.example/workflow/demo'})

if __name__=='__main__':unittest.main()
