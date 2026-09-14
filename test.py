import shutil

input_file = r"C:\Users\admin\Downloads\user_query_detail_total_0907.json"
output_file = "query_200k.json"
num_lines = 200_000

with open(input_file, "r", encoding="utf-8") as src, \
     open(output_file, "w", encoding="utf-8") as dst:

    for i, line in enumerate(src):
        if i >= num_lines:
            break
        dst.write(line)

print(f"完成：已抽取 {min(i + 1, num_lines):,} 行")
print(f"输出文件：{output_file}")