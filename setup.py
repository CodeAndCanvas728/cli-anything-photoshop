from setuptools import find_namespace_packages, setup

setup(
    name="cli-anything-photoshop",
    version="1.0.0",
    description=(
        "A stateful CLI harness for Adobe Photoshop — control the running app "
        "programmatically via AppleScript/ExtendScript."
    ),
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="HKUDS CLI-Anything",
    python_requires=">=3.10",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    package_data={
        "cli_anything.photoshop": ["skills/*.md"],
    },
    include_package_data=True,
    install_requires=[
        "click>=8.0.0",
        "prompt-toolkit>=3.0.0",
    ],
    entry_points={
        "console_scripts": [
            "cli-anything-photoshop=cli_anything.photoshop.photoshop_cli:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: MacOS",
        "Intended Audience :: Developers",
        "Topic :: Multimedia :: Graphics",
    ],
    # NOTE: Adobe Photoshop 2026.app is a hard dependency that cannot be
    # expressed here. Install it from Creative Cloud. The terminal running the
    # CLI needs AppleScript Automation permission for Photoshop.
)
