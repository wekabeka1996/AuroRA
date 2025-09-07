#!/usr/bin/env python3
"""
Simple Mutation Testing Tool for Windows
Alternative to mutmut that doesn't require the 'resource' module
"""

import os
import sys
import ast
import tempfile
import subprocess
import shutil
from pathlib import Path
from typing import List, Dict, Set
import json
import time

class SimpleMutator:
    """Simple mutation testing tool for Windows"""

    def __init__(self, source_dir: str, test_command: str, timeout: int = 30):
        self.source_dir = Path(source_dir)
        self.test_command = test_command
        self.timeout = timeout
        self.mutants_created = 0
        self.mutants_killed = 0
        self.mutants_survived = 0

    def get_python_files(self) -> List[Path]:
        """Get all Python files in the source directory"""
        return list(self.source_dir.rglob("*.py"))

    def run_original_tests(self) -> bool:
        """Run tests on original code to ensure they pass"""
        print("🧪 Running original tests...")
        try:
            result = subprocess.run(
                self.test_command,
                shell=True,
                cwd=self.source_dir.parent,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            if result.returncode == 0:
                print("✅ Original tests pass")
                return True
            else:
                print("❌ Original tests fail - cannot proceed with mutation testing")
                print("STDOUT:", result.stdout)
                print("STDERR:", result.stderr)
                return False
        except subprocess.TimeoutExpired:
            print("⏰ Original tests timed out")
            return False

    def generate_mutants(self, source_file: Path) -> List[Dict]:
        """Generate mutants for a single file"""
        mutants = []

        try:
            with open(source_file, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content, filename=str(source_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.Compare):
                    # Mutate comparison operators
                    for op in node.ops:
                        if isinstance(op, ast.Eq):
                            mutants.append(self._create_mutant(
                                source_file, content, node, "==", "!="
                            ))
                        elif isinstance(op, ast.NotEq):
                            mutants.append(self._create_mutant(
                                source_file, content, node, "!=", "=="
                            ))
                        elif isinstance(op, ast.Lt):
                            mutants.append(self._create_mutant(
                                source_file, content, node, "<", ">="
                            ))
                        elif isinstance(op, ast.Gt):
                            mutants.append(self._create_mutant(
                                source_file, content, node, ">", "<="
                            ))

                elif isinstance(node, ast.BoolOp):
                    # Mutate boolean operators
                    if isinstance(node.op, ast.And):
                        mutants.append(self._create_mutant(
                            source_file, content, node, "and", "or"
                        ))
                    elif isinstance(node.op, ast.Or):
                        mutants.append(self._create_mutant(
                            source_file, content, node, "or", "and"
                        ))

                elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                    # Mutate logical not
                    mutants.append(self._create_mutant(
                        source_file, content, node, "not ", ""
                    ))

        except Exception as e:
            print(f"⚠️  Error parsing {source_file}: {e}")

        return mutants

    def _create_mutant(self, source_file: Path, content: str, node: ast.AST,
                      original: str, mutant: str) -> Dict:
        """Create a mutant by replacing text in the source"""
        # Get the source lines for this node
        lines = content.split('\n')

        # Find the line and column where the mutation should occur
        line_start = node.lineno - 1
        col_start = node.col_offset
        col_end = node.end_col_offset if hasattr(node, 'end_col_offset') else col_start + len(original)

        if line_start < len(lines):
            line = lines[line_start]
            if col_start < len(line) and original in line[col_start:col_end]:
                mutated_line = line[:col_start] + line[col_start:col_end].replace(original, mutant, 1) + line[col_end:]
                lines[line_start] = mutated_line

                return {
                    'file': str(source_file),
                    'line': line_start + 1,
                    'original': original,
                    'mutant': mutant,
                    'mutated_content': '\n'.join(lines)
                }

        return None

    def test_mutant(self, mutant: Dict) -> bool:
        """Test a single mutant"""
        self.mutants_created += 1

        # Create temporary directory for this mutant
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            mutant_file = temp_path / Path(mutant['file']).name

            # Write mutated content
            with open(mutant_file, 'w', encoding='utf-8') as f:
                f.write(mutant['mutated_content'])

            # Copy other necessary files (simplified - just copy the whole directory)
            source_dir = Path(mutant['file']).parent
            for file in source_dir.glob("*.py"):
                if file.name != mutant_file.name:
                    shutil.copy2(file, temp_path / file.name)

            print(f"🧬 Testing mutant: {mutant['file']}:{mutant['line']} {mutant['original']} → {mutant['mutant']}")

            try:
                # Run tests on mutated code
                result = subprocess.run(
                    self.test_command,
                    shell=True,
                    cwd=temp_path,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout
                )

                if result.returncode == 0:
                    print("🟢 Mutant survived (test didn't catch it)")
                    self.mutants_survived += 1
                    return False  # Mutant survived
                else:
                    print("🔴 Mutant killed (test caught it)")
                    self.mutants_killed += 1
                    return True   # Mutant killed

            except subprocess.TimeoutExpired:
                print("⏰ Mutant test timed out - considering as survived")
                self.mutants_survived += 1
                return False

    def run_mutation_testing(self) -> Dict:
        """Run complete mutation testing"""
        print("🚀 Starting Simple Mutation Testing")
        print(f"📁 Source directory: {self.source_dir}")
        print(f"🧪 Test command: {self.test_command}")
        print()

        # First, ensure original tests pass
        if not self.run_original_tests():
            return {"error": "Original tests fail"}

        # Get Python files
        python_files = self.get_python_files()
        print(f"📄 Found {len(python_files)} Python files")

        # Generate and test mutants
        total_mutants = 0
        for file in python_files:
            print(f"\n🔍 Processing {file}")
            mutants = self.generate_mutants(file)

            for mutant in mutants:
                if mutant:
                    self.test_mutant(mutant)
                    total_mutants += 1

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
        print("Usage: python simple_mutator.py <source_dir> <test_command>")
        print("Example: python simple_mutator.py core/signal \"pytest -q\"")
        sys.exit(1)

    source_dir = sys.argv[1]
    test_command = sys.argv[2]
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    mutator = SimpleMutator(source_dir, test_command, timeout)
    results = mutator.run_mutation_testing()

    # Save results
    output_file = f"mutation_results_{Path(source_dir).name}_{int(time.time())}.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n💾 Results saved to: {output_file}")

if __name__ == "__main__":
    main()