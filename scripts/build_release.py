#!/usr/bin/env python3
"""
AURORA Release Build Script
Створює wheel та docker образ для RC/GA релізів
"""
import os
import sys
import subprocess
import argparse
from pathlib import Path

def run_command(cmd, check=True):
    """Виконати команду та показати вивід"""
    print(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    
    if check and result.returncode != 0:
        raise SystemExit(f"Command failed with exit code {result.returncode}")
    
    return result

def get_version():
    """Читаємо версію з VERSION файлу"""
    # Try relative to script first, then project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    for version_file in [script_dir / "VERSION", project_root / "VERSION"]:
        if version_file.exists():
            return version_file.read_text().strip()
    
    raise SystemExit("VERSION file not found")

def build_wheel():
    """Створити Python wheel"""
    print("🏗️  Building Python wheel...")
    
    # Створюємо setup.py для wheel build
    setup_py_content = f'''
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
    package_data={{
        "": ["*.yaml", "*.json", "*.txt", "VERSION"]
    }},
    entry_points={{
        "console_scripts": [
            "aurora-api=api.service:main",
            "aurora-schema-lint=tools.schema_linter:main",
        ]
    }},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Financial and Insurance Industry",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
'''
    
    with open("setup.py", "w") as f:
        f.write(setup_py_content)
    
    # Build wheel
    run_command("python setup.py bdist_wheel")
    
    print("✅ Wheel built successfully")

def build_docker(version, registry="lla"):
    """Створити Docker образ"""
    print(f"🐳 Building Docker image...")
    
    tag = f"{registry}:r2-{version}"
    cmd = f"docker build --build-arg VERSION={version} -t {tag} ."
    
    run_command(cmd)
    
    # Tag as latest RC if it's RC build
    if "rc" in version:
        latest_rc_tag = f"{registry}:r2-latest-rc"
        run_command(f"docker tag {tag} {latest_rc_tag}")
        print(f"✅ Docker image built: {tag}, {latest_rc_tag}")
    else:
        print(f"✅ Docker image built: {tag}")
    
    return tag

def create_git_tag(version):
    """Створити Git tag"""
    tag_name = f"v{version}"
    
    print(f"🏷️  Creating Git tag: {tag_name}")
    
    # Check if tag already exists
    result = run_command(f"git tag -l {tag_name}", check=False)
    if result.stdout.strip():
        print(f"⚠️  Tag {tag_name} already exists, skipping...")
        return tag_name
    
    # Create tag
    message = f"R2 Hardening RC: smoke green, metrics, linter, docs" if "rc" in version else f"Release {version}"
    run_command(f'git tag -a {tag_name} -m "{message}"')
    
    print(f"✅ Git tag created: {tag_name}")
    return tag_name

def push_artifacts(version, registry="lla", push_git=False):
    """Push артефактів"""
    if push_git:
        print("📤 Pushing Git tags...")
        run_command("git push --tags")
    
    # Docker push можна додати коли буде registry
    print(f"📋 Artifacts ready:")
    print(f"   - Docker image: {registry}:r2-{version}")
    print(f"   - Wheel: dist/aurora_trading-{version}-py3-none-any.whl")
    print(f"   - Git tag: v{version}")

def main():
    parser = argparse.ArgumentParser(description="Build AURORA release artifacts")
    parser.add_argument("--wheel", action="store_true", help="Build Python wheel")
    parser.add_argument("--docker", action="store_true", help="Build Docker image")
    parser.add_argument("--git-tag", action="store_true", help="Create Git tag")
    parser.add_argument("--push", action="store_true", help="Push Git tags (use with --git-tag)")
    parser.add_argument("--all", action="store_true", help="Build all artifacts")
    parser.add_argument("--registry", default="lla", help="Docker registry prefix")
    
    args = parser.parse_args()
    
    if not any([args.wheel, args.docker, args.git_tag, args.all]):
        parser.print_help()
        return
    
    version = get_version()
    print(f"🚀 Building AURORA {version}")
    
    try:
        if args.all or args.wheel:
            build_wheel()
        
        if args.all or args.docker:
            build_docker(version, args.registry)
        
        if args.all or args.git_tag:
            create_git_tag(version)
        
        if args.push and (args.git_tag or args.all):
            push_artifacts(version, args.registry, push_git=True)
        elif not args.push:
            push_artifacts(version, args.registry, push_git=False)
        
        print(f"🎉 Build completed successfully for version {version}")
        
    except Exception as e:
        print(f"❌ Build failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()