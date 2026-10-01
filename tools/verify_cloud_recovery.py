"""Verify recovered delivery files against the cloud commit's recorded Git tree.

No Git objects, index entries or refs are written. User architecture edits and
new implementation files are intentionally excluded from the reconstructed tree.
"""
from hashlib import sha1
from pathlib import Path
import subprocess

BASE = "9af272e37f8ea7fd32aae1355ac076b6ca2275c2"
EXPECTED = "253e0f6152b1d6bffdd5dd37f7adb2b25768d045"
PATHS = [
    "curriculum-sampler-implementation.md", "curriculum-sampler-audit.md",
    "curriculum_sampler/__init__.py", "curriculum_sampler/synthetic.py",
    "curriculum_sampler/README.md", "curriculum_sampler/__main__.py",
    "examples/curriculum-sampler-tests.txt", "task_advisor/curriculum.py",
    "task_advisor/instrumentation.py", "task_advisor/core.py",
    "task_advisor/execution.py", "task_advisor/evaluation.py", "task_advisor/worker.py",
    "examples/curriculum-sampler-smoke.json", "task_advisor/loop.py",
    "task_library/governance.py", "task_library/library.py", "task_library/regions.py",
    "taskgen/core.py", "taskgen/parameters.py", "tests/test_curriculum_sampler.py",
]


def object_hash(kind, data):
    return sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).digest()


def verify(source_root="artifacts/cloud-recovery"):
    files = {}
    for row in subprocess.check_output(["git", "ls-tree", "-rz", BASE]).split(b"\0"):
        if not row:
            continue
        header, path = row.split(b"\t", 1)
        mode, kind, digest = header.split()
        files[path.decode()] = (mode, bytes.fromhex(digest.decode()))
    for path in PATHS:
        # Git checkouts may convert text files to CRLF on Windows. The cloud
        # commit stores LF; verify its bytes independently of checkout settings.
        content = (Path(source_root) / path).read_bytes().replace(b"\r\n", b"\n")
        files[path] = (b"100644", object_hash("blob", content))
    root = {}
    for path, metadata in files.items():
        node = root
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = metadata
    def tree(node):
        result = bytearray()
        for name in sorted(node, key=lambda n: (n + ("/" if isinstance(node[n], dict) else "")).encode()):
            value = node[name]
            mode, digest = (b"40000", tree(value)) if isinstance(value, dict) else value
            result.extend(mode + b" " + name.encode() + b"\0" + digest)
        return object_hash("tree", bytes(result))
    digest = tree(root).hex()
    if digest != EXPECTED:
        raise ValueError(f"recovered tree {digest} differs from recorded {EXPECTED}")
    return {"recovered_files": len(PATHS), "verified_tree": digest,
            "reported_cloud_commit": "42123af55c3781880b16585b7afbe770338b1e1d"}


if __name__ == "__main__":
    print(verify())
