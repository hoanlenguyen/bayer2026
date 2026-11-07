import os

# Must run before app modules read settings.
os.environ["LLM_PROVIDER"] = "mock"
os.environ["MONGODB_URI"] = ""
