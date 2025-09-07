#!/usr/bin/env python3
"""
Ultra-Simple Mutation Testing Tool for Windows
Works without complex imports - focuses on basic Python syntax mutations
"""

import os
import sys
import ast
import tempfile
import subprocess
import shutil
from pathlib import Path
from typing import List, Dict
import json
import time

class UltraSimpleMutator:
    """Ultra-simple mutation testing tool for basic Python files"""

    def __init__(self, source_dir: str, test_command: str, timeout: int = 30):
        self.source_dir = Path(source_dir)
        self.test_command = test_command
        self.timeout = timeout
        self.mutants_created = 0
        self.mutants_killed = 0
        self.mutants_survived = 0

    def get_simple_python_files(self) -> List[Path]:
        """Get Python files that are likely to have simple mutations"""
        python_files = []
        
        # Handle both directory and single file cases
        if self.source_dir.is_file():
            files_to_check = [self.source_dir]
        else:
            files_to_check = list(self.source_dir.rglob("*.py"))
        
        for file in files_to_check:
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()
                # Skip files with complex imports or very long files
                if len(content) > 100000:  # Skip very large files
                    continue
                # Allow files in core/aurora but skip other complex imports
                if 'import' in content and 'api.' in content and 'core.' not in content[:content.find('api.')] and 'from core.' not in content:
                    continue  # Skip files with complex api imports but not core imports
                python_files.append(file)
            except:
                continue
        return python_files

    def create_simple_test_file(self) -> str:
        """Create a simple test file that can be run standalone"""
        test_content = '''
# Simple test file for mutation testing
def test_comparisons():
    """Test basic comparisons"""
    x = 5
    y = 10
    z = 3

    assert x < y
    assert x != y
    assert y > x
    assert x <= 5
    assert y >= 10
    assert z < x

def test_boolean_logic():
    """Test boolean operations"""
    a = True
    b = False
    c = True

    assert a and not b
    assert a or b
    assert not (a and b)
    assert (a or b) and c
    assert a and b or c

def test_arithmetic():
    """Test arithmetic operations"""
    x = 10
    y = 3

    assert x + y == 13
    assert x - y == 7
    assert x * y == 30
    assert x // y == 3
    assert x % y == 1

def test_conditionals():
    """Test conditional logic"""
    x = 5

    if x > 0:
        result = "positive"
    else:
        result = "non-positive"

    assert result == "positive"
    assert x > 0 and x < 10

if __name__ == "__main__":
    import sys
    tests = [test_comparisons, test_boolean_logic, test_arithmetic, test_conditionals]
    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {test.__name__}: {e}")
            failed += 1

    print(f"Results: {passed} passed, {failed} failed")
    if failed > 0:
        sys.exit(1)
'''
        return test_content

    def run_original_tests(self) -> bool:
        """Run tests on original code"""
        print("🧪 Running original tests...")

        try:
            # Use the provided test command instead of creating simple tests
            # For Windows, handle the command properly
            if isinstance(self.test_command, str):
                # Use shell=True for Windows command parsing
                result = subprocess.run(
                    self.test_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=os.getcwd()
                )
            else:
                result = subprocess.run(
                    self.test_command,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=os.getcwd()
                )

            if result.returncode == 0:
                print("✅ Original tests pass")
                return True
            else:
                print("❌ Original tests fail")
                print("STDOUT:", result.stdout[-500:])  # Last 500 chars
                print("STDERR:", result.stderr[-500:])
                return False

        except subprocess.TimeoutExpired:
            print("⏰ Original tests timed out")
            return False

    def generate_mutants(self, source_file: Path) -> List[Dict]:
        """Generate simple mutants for a file"""
        mutants = []

        try:
            with open(source_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Simple string-based mutations (not AST-based for simplicity)
            lines = content.split('\n')

            for i, line in enumerate(lines):
                # Skip comments and imports
                stripped = line.strip()
                if stripped.startswith('#') or stripped.startswith('import') or stripped.startswith('from'):
                    continue
                if not stripped:  # Skip empty lines
                    continue

                # Simple mutations for all operators
                mutations = []

                # Boolean operators (main focus for risk package)
                if ' or ' in line:
                    mutations.append(line.replace(' or ', ' and '))
                if ' and ' in line:
                    mutations.append(line.replace(' and ', ' or '))

                # Comparison operators
                if ' < ' in line:
                    mutations.append(line.replace(' < ', ' > '))
                if ' > ' in line:
                    mutations.append(line.replace(' > ', ' < '))
                if ' == ' in line:
                    mutations.append(line.replace(' == ', ' != '))
                if ' != ' in line:
                    mutations.append(line.replace(' != ', ' == '))
                if ' <= ' in line:
                    mutations.append(line.replace(' <= ', ' >= '))
                if ' >= ' in line:
                    mutations.append(line.replace(' >= ', ' <= '))

                # Arithmetic operators
                if ' + ' in line:
                    mutations.append(line.replace(' + ', ' - '))
                if ' - ' in line:
                    mutations.append(line.replace(' - ', ' + '))
                if ' * ' in line:
                    mutations.append(line.replace(' * ', ' / '))
                if ' / ' in line:
                    mutations.append(line.replace(' / ', ' * '))

                for mutated_line in mutations:
                    if mutated_line != line:
                        new_lines = lines.copy()
                        new_lines[i] = mutated_line
                        mutants.append({
                            'file': str(source_file),
                            'line': i + 1,
                            'original': line.strip(),
                            'mutant': mutated_line.strip(),
                            'mutated_content': '\n'.join(new_lines)
                        })

        except Exception as e:
            print(f"⚠️  Error processing {source_file}: {e}")

        return mutants

    def test_mutant(self, mutant: Dict) -> bool:
        """Test a single mutant"""
        self.mutants_created += 1

        # Create temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Copy entire source directory to temp
            for file_path in self.source_dir.rglob("*"):
                if file_path.is_file():
                    relative_path = file_path.relative_to(self.source_dir)
                    dest_path = temp_path / relative_path
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file_path, dest_path)

            # Write mutated file
            source_file = Path(mutant['file'])
            mutant_file = temp_path / source_file.name
            with open(mutant_file, 'w', encoding='utf-8') as f:
                f.write(mutant['mutated_content'])

            print(f"🧬 Testing mutant: {mutant['file']}:{mutant['line']} {mutant['original']} → {mutant['mutant']}")

            try:
                # Run the provided test command in the temp directory
                # For Windows, handle the command properly
                if isinstance(self.test_command, str):
                    # Use shell=True for Windows command parsing
                    result = subprocess.run(
                        self.test_command,
                        shell=True,
                        cwd=temp_path,
                        capture_output=True,
                        text=True,
                        timeout=self.timeout
                    )
                else:
                    result = subprocess.run(
                        self.test_command,
                        cwd=temp_path,
                        capture_output=True,
                        text=True,
                        timeout=self.timeout
                    )

                if result.returncode == 0:
                    print("🟢 Mutant survived")
                    self.mutants_survived += 1
                    return False
                else:
                    print("🔴 Mutant killed")
                    self.mutants_killed += 1
                    return True

            except subprocess.TimeoutExpired:
                print("⏰ Mutant test timed out")
                self.mutants_survived += 1
                return False

    def run_mutation_testing(self) -> Dict:
        """Run complete mutation testing"""
        print("🚀 Starting Ultra-Simple Mutation Testing")
        print(f"📁 Source directory: {self.source_dir}")
        print()

        # First, ensure tests pass
        if not self.run_original_tests():
            return {"error": "Original tests fail"}

        # Get simple Python files
        python_files = self.get_simple_python_files()
        print(f"📄 Found {len(python_files)} simple Python files")

        # Generate and test mutants
        for file in python_files:  # Process all files
            print(f"\n🔍 Processing {file}")
            mutants = self.generate_mutants(file)

            for mutant in mutants:  # Process all mutants
                self.test_mutant(mutant)

        # Calculate results
        mutation_score = (self.mutants_killed / self.mutants_created * 100) if self.mutants_created > 0 else 0

        results = {
            "total_files": len(python_files),
            "total_mutants": self.mutants_created,
            "killed_mutants": self.mutants_killed,
            "survived_mutants": self.mutants_survived,
            "mutation_score": round(mutation_score, 2),
            "timestamp": time.time()
        }

        print("\n📊 Mutation Testing Results:")
        print(f"   Total mutants: {results['total_mutants']}")
        print(f"   Killed: {results['killed_mutants']}")
        print(f"   Survived: {results['survived_mutants']}")
        print(f"   Mutation score: {results['mutation_score']}%")

        return results

def main():
    if len(sys.argv) < 3:
        print("Usage: python ultra_simple_mutator.py <source_dir> <test_command>")
        print("Example: python ultra_simple_mutator.py core/signal \"python test.py\"")
        sys.exit(1)

    source_dir = sys.argv[1]
    test_command = sys.argv[2]
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    mutator = UltraSimpleMutator(source_dir, test_command, timeout)
    results = mutator.run_mutation_testing()

    # Save results
    output_file = f"ultra_mutation_results_{Path(source_dir).name}_{int(time.time())}.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n💾 Results saved to: {output_file}")

if __name__ == "__main__":
    main()