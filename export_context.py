import os

# Tên file xuất ra
OUTPUT_FILE = 'project_context.txt'

# Các thư mục và file không cần thiết cho AI đọc
IGNORE_DIRS = {'.git', 'venv', 'env', '__pycache__', 'media', 'node_modules', 'migrations', 'static'}
ALLOWED_EXTS = {'.py', '.html', '.css', '.js', '.txt'}

def generate_context():
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
        # 1. In cấu trúc thư mục
        outfile.write("========================================\n")
        outfile.write("CẤU TRÚC THƯ MỤC DỰ ÁN\n")
        outfile.write("========================================\n\n")
        for root, dirs, files in os.walk('.'):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            level = root.replace('.', '').count(os.sep)
            indent = ' ' * 4 * level
            outfile.write(f'{indent}{os.path.basename(root)}/\n')
            subindent = ' ' * 4 * (level + 1)
            for f in files:
                if any(f.endswith(ext) for ext in ALLOWED_EXTS):
                    outfile.write(f'{subindent}{f}\n')

        # 2. In nội dung từng file
        outfile.write("\n\n========================================\n")
        outfile.write("NỘI DUNG SOURCE CODE\n")
        outfile.write("========================================\n")
        for root, dirs, files in os.walk('.'):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for file in files:
                if any(file.endswith(ext) for ext in ALLOWED_EXTS) and file != 'export_context.py' and file != OUTPUT_FILE:
                    filepath = os.path.join(root, file)
                    outfile.write(f"\n\n{'='*60}\n")
                    outfile.write(f"--- FILE: {filepath} ---\n")
                    outfile.write(f"{'='*60}\n\n")
                    try:
                        with open(filepath, 'r', encoding='utf-8') as infile:
                            outfile.write(infile.read())
                    except Exception as e:
                        outfile.write(f"[Lỗi không thể đọc file: {e}]\n")
                        
    print(f"✅ Đã gom toàn bộ code thành công vào file: {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_context()