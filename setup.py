
from setuptools import setup, find_packages

with open("VERSION", "r") as f:
    version = f.read().strip()

with open("requirements.txt", "r") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="aurora-trading",
    version=version,
    description="AURORA v1.2 - Certified Regime-Aware Trading System",
    packages=find_packages(),
    install_requires=requirements,
    python_requires=">=3.10",
    include_package_data=True,
    package_data={
        "": ["*.yaml", "*.json", "*.txt", "VERSION"]
    },
    entry_points={
        "console_scripts": [
            "aurora-api=api.service:main",
            "aurora-schema-lint=tools.schema_linter:main",
        ]
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Financial and Insurance Industry",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
