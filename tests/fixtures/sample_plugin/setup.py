from setuptools import setup, find_packages

setup(
    name="studyagent-sample-plugin",
    version="0.1.0",
    packages=find_packages(),
    entry_points={
        "studyagent.plugins": [
            "sample = sample_plugin",
        ],
    },
)
