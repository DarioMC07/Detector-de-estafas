"""Mensaje Seguro: API y aplicación web local."""

import os


def _silenciar_loky() -> None:
    """En Windows 11, joblib/loky cuenta núcleos físicos con "wmic" (ya no existe) y
    vuelca una traza inofensiva en la consola. Se le da el valor directamente."""
    os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 1))
    try:
        from joblib.externals.loky.backend import context

        if getattr(context, "physical_cores_cache", None) is None:
            context.physical_cores_cache = os.cpu_count() or 1
    except Exception:
        pass


_silenciar_loky()
