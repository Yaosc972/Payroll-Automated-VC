"""Publish a consistent local SkillHub release; unchanged content is idempotent."""
import argparse
from pathlib import Path
from bonus_platform.engine.domestic_labor.skillhub import export_release


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("outputs/domestic-skillhub-latest"))
    args = parser.parse_args()
    catalog = export_release(args.output)
    print(f"已同步 {len(catalog['skills'])} 份 Skill；累计 {len(catalog['releases'])} 条上新记录；输出：{args.output.resolve()}")


if __name__ == "__main__":
    main()
