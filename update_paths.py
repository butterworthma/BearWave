#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BearWave Path Updater
====================

Updates hardcoded paths in BearWave field trial and NVIS model scripts
to use relative paths for portability.

Author: Research Team
License: MIT
"""

import os
import re
from pathlib import Path

def update_file_paths(file_path):
    """Update hardcoded paths in a Python file to use relative paths"""
    
    print(f"📝 Processing: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        changes_made = 0
        
        # Common path patterns to replace
        path_replacements = [
            # Desktop paths
            (r'/Users/[^/]+/Desktop/[^\'"\s]+\.xlsx', 'data/field_trial_data.xlsx'),
            (r'/Users/[^/]+/Desktop/[^\'"\s]+\.csv', 'data/field_trial_data.csv'),
            (r'/Users/[^/]+/Desktop/[^\'"\s]+\.png', 'output/generated_chart.png'),
            
            # Specific file patterns
            (r'/Users/[^/]+/Desktop/Marks_phD/[^\'"\s]+', 'output/analysis_result.png'),
            (r'/Users/[^/]+/Desktop/final_5\.xlsx', 'data/belpha_data.xlsx'),
            (r'/Users/[^/]+/Desktop/GW3RNP-no-TX-\s*Pondy\.xlsx', 'data/clydach_data.xlsx'),
            (r'/Users/[^/]+/Desktop/GW3RNP-no-TX-Rhods\.xlsx', 'data/brockweir_data.xlsx'),
            (r'/Users/[^/]+/Desktop/G3RNP-no-TX-Belpha-2-cut\.xlsx', 'data/belpha_data.xlsx'),
            
            # Generic desktop patterns
            (r'/Users/[^/]+/Desktop/', 'data/'),
        ]
        
        # Apply replacements
        for pattern, replacement in path_replacements:
            new_content = re.sub(pattern, replacement, content)
            if new_content != content:
                changes_made += 1
                content = new_content
                print(f"  ✅ Replaced: {pattern[:50]}... → {replacement}")
        
        # Save updated content if changes were made
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"  💾 Saved {changes_made} changes to {file_path}")
        else:
            print(f"  ℹ️  No changes needed for {file_path}")
            
        return changes_made
        
    except Exception as e:
        print(f"  ❌ Error processing {file_path}: {e}")
        return 0

def update_all_paths():
    """Update paths in all Python files in the repository"""
    
    print("🔧 BEARWAVE PATH UPDATER")
    print("="*50)
    
    # Get repository root
    repo_root = Path.cwd()
    print(f"📁 Repository root: {repo_root}")
    
    # Find all Python files
    python_files = []
    for directory in ['field_trials', 'nvis_models']:
        dir_path = repo_root / directory
        if dir_path.exists():
            python_files.extend(dir_path.glob('*.py'))
    
    print(f"📊 Found {len(python_files)} Python files to process")
    
    total_changes = 0
    
    # Process each file
    for file_path in python_files:
        changes = update_file_paths(file_path)
        total_changes += changes
    
    print(f"\n🎉 PATH UPDATE COMPLETE!")
    print(f"📊 Total files processed: {len(python_files)}")
    print(f"🔧 Total changes made: {total_changes}")
    
    if total_changes > 0:
        print(f"\n📋 NEXT STEPS:")
        print(f"1. Place your data files in the data/ directory:")
        print(f"   - data/belpha_data.xlsx")
        print(f"   - data/clydach_data.xlsx") 
        print(f"   - data/brockweir_data.xlsx")
        print(f"2. Test the scripts:")
        print(f"   python field_trials/belpha_analysis.py")
        print(f"3. Generated charts will be saved to output/")
    
    return total_changes

def main():
    """Main function"""
    try:
        update_all_paths()
    except KeyboardInterrupt:
        print("\n\n⚠️ Update interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")

if __name__ == "__main__":
    main()
