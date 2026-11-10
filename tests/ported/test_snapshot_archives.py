import json
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from awm_adm.engine import Instance, SnapshotPackage, read_snapshot, validate_snapshot, write_snapshot
from awm_adm.engine.errors import ADMError, InvalidIR


class SnapshotArchiveTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.package = Instance(mode="forward").export_snapshot()

    def archive(self, entries, *, compression=zipfile.ZIP_STORED):
        path = self.root / "bad.adm"
        with warnings.catch_warnings(), zipfile.ZipFile(path, "w", compression=compression) as archive:
            warnings.simplefilter("ignore", UserWarning)
            for filename, data in entries:
                archive.writestr(filename, data)
        return path

    def test_duplicate_traversal_symlink_directory_and_extra_members_rejected(self):
        valid = [("manifest.json", self.package.manifest), *self.package.files.items()]
        symlink = zipfile.ZipInfo("link")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases = [
            [valid[0]],
            [("../escape", b"x")],
            [("/absolute", b"x")],
            [(symlink, b"outside")],
            [("directory/", b"")],
            [("extra", b"{}")],
        ]
        for extra in cases:
            path = self.archive([*valid, *extra])
            with self.subTest(extra=extra[0][0]), self.assertRaises(ADMError):
                read_snapshot(path)
        self.assertFalse((self.root.parent / "escape").exists())

    def test_compression_corruption_and_archive_symlinks_rejected(self):
        valid = [("manifest.json", self.package.manifest), *self.package.files.items()]
        with self.assertRaises(ADMError):
            read_snapshot(self.archive(valid, compression=zipfile.ZIP_DEFLATED))
        path = self.root / "invalid.adm"
        path.write_bytes(b"not a ZIP archive")
        with self.assertRaises(InvalidIR):
            read_snapshot(path)
        good = self.root / "good.adm"
        write_snapshot(self.package, good)
        link = self.root / "linked.adm"
        link.symlink_to(good)
        with self.assertRaises(InvalidIR):
            read_snapshot(link)

    def test_exact_manifest_bytes_define_package_identity(self):
        changed = SnapshotPackage(
            json.dumps(json.loads(self.package.manifest), indent=2).encode(), self.package.files
        )
        self.assertNotEqual(changed.package_id, self.package.package_id)
        self.assertEqual(
            validate_snapshot(changed)["model"].version, validate_snapshot(self.package)["model"].version
        )
