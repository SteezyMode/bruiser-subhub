"""Offline regression for the validator installer and confirmed deployed SHA."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import service


SCRIPT = Path(__file__).parent/'tools/deploy_validator.py'
SPEC = importlib.util.spec_from_file_location('deploy_validator_check', SCRIPT)
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


class ValidatorDeploymentTests(unittest.TestCase):
    def test_expected_sha_is_actual_installed_batchfix_blob(self):
        # Checked against service.py in GitHub main at commit 7cb3b8b,
        # and the real OptiPlex hash reported by the guarded installer.
        self.assertEqual(deploy.EXPECTED_OLD_GIT_BLOB,
                         '896b245357a9e3b1d72e7be83cd5268108d8da20')

    def test_known_previous_version_is_upgraded_with_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)/'bruiser-pilot'
            target = base/'subhub1/service.py'
            target.parent.mkdir(parents=True)
            old_bytes = b'# previous batch-fixed source placeholder\n'
            target.write_bytes(old_bytes)
            candidate = base/'subhub1/service.candidate.py'
            shutil.copyfile(Path(service.__file__),candidate)
            root = base/'subhub1-state'
            def hash_of(p):
                if p==target:
                    return deploy.EXPECTED_OLD_GIT_BLOB
                return 'new-candidate-blob'
            with patch.object(deploy,'blob',side_effect=hash_of):
                deploy.install(base,root,target,candidate)
            self.assertEqual(target.read_bytes(),Path(service.__file__).read_bytes())
            self.assertFalse(candidate.exists())
            backups=list(target.parent.glob('service.py.before-validator-*'))
            self.assertEqual(len(backups),1)
            self.assertEqual(backups[0].read_bytes(),old_bytes)

    def test_unknown_version_aborts_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'bruiser-pilot'
            target=base/'subhub1/service.py'
            target.parent.mkdir(parents=True)
            target.write_text('existing custom version')
            candidate=base/'subhub1/service.candidate.py'
            shutil.copyfile(Path(service.__file__),candidate)
            with patch.object(deploy,'blob',side_effect=lambda p:'unknown' if p==target else 'new'):
                with self.assertRaisesRegex(RuntimeError,'differs from known installed'):
                    deploy.install(base,base/'subhub1-state',target,candidate)
            self.assertEqual(target.read_text(),'existing custom version')
            self.assertTrue(candidate.exists())
            self.assertEqual(list(target.parent.glob('service.py.before-validator-*')),[])


if __name__=='__main__':
    unittest.main()
