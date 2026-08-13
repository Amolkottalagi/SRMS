import os
import zipfile

def zip_project():
    zip_name = "srms_python.zip"
    exclude_dirs = {".venv", "__pycache__", ".git", ".idea", ".vscode", "tests/__pycache__", "utils/__pycache__"}
    exclude_files = {"srms.db", "srms_python.zip", "run_public.py"}

    print(f"Creating {zip_name}...")
    count = 0
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk('.'):
            # Modify dirs in-place to exclude unwanted directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                if file in exclude_files or file.endswith('.pyc'):
                    continue
                file_path = os.path.join(root, file)
                # Use relative path for zip entry
                arc_name = os.path.relpath(file_path, '.')
                zipf.write(file_path, arc_name)
                print(f"  Added: {arc_name}")
                count += 1
                
    print(f"\nSuccessfully created {zip_name} with {count} files!")
    print("You can upload this zip file directly to PythonAnywhere and unzip it via the console.")

if __name__ == '__main__':
    zip_project()
