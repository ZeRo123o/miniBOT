def get_storage():
    from app.storage.factory import get_storage as _get_storage

    return _get_storage()

__all__ = ["get_storage"]
