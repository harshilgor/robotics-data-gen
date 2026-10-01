"""Training exclusion survives metadata changes and new executable revisions."""
from taskgen.core import fingerprint
from task_library.library import structural_signature
from taskgen.parameters import contains


def training_reserved(repository, task, values):
    signature = fingerprint(structural_signature(task))
    for reservation in repository.records('heldout_family'):
        if reservation.get('structural_hash') != signature:
            continue
        restrictions = reservation.get('parameter_restrictions')
        if not restrictions or all(name in values and contains(spec,values[name]) for name,spec in restrictions.items()):
            return True
    return False
