"""Process locks for the runnable Unix local factory; released on process death."""
from contextlib import contextmanager

@contextmanager
def exclusive(path):
    import fcntl
    with open(path,'a') as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('another local factory process owns '+str(path)) from exc
        try: yield
        finally: fcntl.flock(handle,fcntl.LOCK_UN)
