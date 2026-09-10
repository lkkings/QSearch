"""Split a JSONL file into multiple parts by line count."""

import argparse
from pathlib import Path


def split_jsonl(input_path: Path, num_parts: int, output_dir: Path = None):
    """Split a JSONL file into multiple parts.

    Args:
        input_path: Path to input JSONL file.
        num_parts: Number of parts to split into.
        output_dir: Output directory (defaults to same as input).
    """
    if output_dir is None:
        output_dir = input_path.parent

    output_dir.mkdir(parents=True, exist_ok=True)

    # Count total lines
    with open(input_path, 'r', encoding='utf-8') as f:
        total_lines = sum(1 for line in f if line.strip())

    lines_per_part = (total_lines + num_parts - 1) // num_parts  # Ceiling division

    print(f"Total lines: {total_lines:,}")
    print(f"Lines per part: {lines_per_part:,}")
    print(f"Splitting into {num_parts} parts...")

    # Generate output file pattern
    stem = input_path.stem  # filename without extension
    suffix = input_path.suffix

    # Split the file
    with open(input_path, 'r', encoding='utf-8') as infile:
        part_num = 1
        line_count = 0
        outfile = None

        for line in infile:
            line = line.strip()
            if not line:
                continue

            # Open new output file if needed
            if line_count % lines_per_part == 0:
                if outfile:
                    outfile.close()
                    print(f"  ✓ Part {part_num - 1}: {line_count - (part_num - 2) * lines_per_part:,} lines")

                output_path = output_dir / f"{stem}_part{part_num}{suffix}"
                outfile = open(output_path, 'w', encoding='utf-8')
                part_num += 1

            outfile.write(line + '\n')
            line_count += 1

        if outfile:
            outfile.close()
            print(f"  ✓ Part {part_num - 1}: {line_count - (part_num - 2) * lines_per_part:,} lines")

    print(f"\n✓ Successfully split into {num_parts} files in {output_dir}")


def main():
    parser = argparse.ArgumentParser(description='Split a JSONL file into multiple parts')
    parser.add_argument('--input', type=str, required=True, help='Path to input JSONL file')
    parser.add_argument('--parts', type=int, default=4, help='Number of parts to split into')
    parser.add_argument('--output-dir', type=str, help='Output directory (default: same as input)')

    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir) if args.output_dir else None

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return

    split_jsonl(input_path, args.parts, output_dir)


if __name__ == '__main__':
    main()
