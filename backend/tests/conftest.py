import os

# Must run before app modules read settings.
os.environ["STAGE_DELAY"] = "0"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["MONGODB_URI"] = ""

os.environ["STORE_MODE"] = "memory"
