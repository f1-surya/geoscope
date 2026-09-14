import os
import tempfile

# Importing app.main builds the global Store and configures logging, which would
# otherwise write into the real per-user data directory. Point everything at a
# throwaway directory before any app module is imported.
os.environ.setdefault("GEOSCOPE_DATA_DIR", tempfile.mkdtemp(prefix="geoscope-tests-"))
os.environ.setdefault("GEOSCOPE_LOG_LEVEL", "WARNING")
