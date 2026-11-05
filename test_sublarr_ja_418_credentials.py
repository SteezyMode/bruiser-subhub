"""Offline tests for Sublarr 1.18 scratch provider credential loading.

These tests create only disposable SQLite and Fernet fixture files.
No real API keys, network, subtitles, or media are accessed.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cryptography.fernet import Fernet

from tools.sublarr_ja_418_scratch_inspect import _existing_provider_credentials


class CredentialReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.td=tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.folder=Path(self.td.name)
        self.db=self.folder/"sublarr.db"
        with sqlite3.connect(self.db) as con:
            con.execute("CREATE TABLE config_entries (key TEXT PRIMARY KEY, value TEXT)")
            con.commit()

    def settings(self):
        return SimpleNamespace(
            opensubtitles_api_key="",
            opensubtitles_username="",
            opensubtitles_password="",
            config_dir=str(self.folder),
            get_database_url=lambda: "sqlite:///"+str(self.db),
        )

    def put(self, **data):
        with sqlite3.connect(self.db) as con:
            con.executemany(
                "INSERT INTO config_entries(key,value) VALUES (?,?)",
                [(k,v) for k,v in data.items()])
            con.commit()

    def test_finds_live_db_settings_missing_from_fresh_process(self):
        self.put(opensubtitles_api_key="key-for-offline-test",
                 opensubtitles_username="test-user",
                 opensubtitles_password="test-password")
        credentials=_existing_provider_credentials(self.settings())
        self.assertEqual(credentials,{"api_key":"key-for-offline-test",
                                      "username":"test-user",
                                      "password":"test-password"})
        # The helper must never create, change, remove or migrate config rows.
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM config_entries").fetchone()[0],3)

    def test_decrypts_existing_key_without_modifying_encrypted_db(self):
        secret_key=Fernet.generate_key()
        (self.folder/".encryption_key").write_bytes(secret_key)
        encryptor=Fernet(secret_key)
        stored="enc:v1:"+encryptor.encrypt(b"private-test-key").decode("ascii")
        self.put(opensubtitles_api_key=stored)
        result=_existing_provider_credentials(self.settings())
        self.assertEqual(result["api_key"],"private-test-key")
        with sqlite3.connect(self.db) as con:
            saved=con.execute("SELECT value FROM config_entries WHERE key='opensubtitles_api_key'").fetchone()[0]
        self.assertEqual(saved,stored)

    def test_missing_key_file_does_not_create_one(self):
        self.put(opensubtitles_api_key="enc:v1:fake-token")
        with self.assertRaisesRegex(RuntimeError,"key file missing"):
            _existing_provider_credentials(self.settings())
        self.assertFalse((self.folder/".encryption_key").exists())

    def test_missing_credentials_refuse(self):
        with self.assertRaisesRegex(RuntimeError,"API key unavailable"):
            _existing_provider_credentials(self.settings())

    def test_wrong_master_key_refuse(self):
        self.put(opensubtitles_api_key="enc:v1:"+Fernet(Fernet.generate_key()).encrypt(
            b"unused-key").decode("ascii"))
        (self.folder/".encryption_key").write_bytes(Fernet.generate_key())
        with self.assertRaisesRegex(RuntimeError,"could not be read"):
            _existing_provider_credentials(self.settings())

    def test_reject_non_sqlite_backend(self):
        settings=self.settings()
        settings.get_database_url=lambda:"postgresql://somewhere/db"
        with self.assertRaisesRegex(RuntimeError,"Unsupported DB"):
            _existing_provider_credentials(settings)


if __name__=="__main__":
    unittest.main()
