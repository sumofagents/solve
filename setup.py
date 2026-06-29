from setuptools import find_packages, setup

setup(
    name="solve",
    version="0.1.0",
    description="Verifier-mediated bounded generation over Lean/mathlib.",
    packages=find_packages("src"),
    package_dir={"": "src"},
    install_requires=["pydantic>=2", "PyYAML>=6"],
    extras_require={"dev": ["pytest>=8"]},
    entry_points={"console_scripts": ["solve=solve.cli:main"]},
)
