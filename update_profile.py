"""Interactive Q&A to add new experiences/projects to profile.yaml."""
from __future__ import annotations

import yaml
from pathlib import Path


def main():
    path = Path("profile.yaml")
    if not path.exists():
        print("profile.yaml not found.")
        return

    with open(path) as f:
        profile = yaml.safe_load(f)

    print("\nWhat would you like to add?")
    print("  1. New project")
    print("  2. New skill")
    print("  3. New certification/training")
    choice = input("\nChoice (1/2/3): ").strip()

    if choice == "1":
        name = input("Project name: ").strip()
        raw_context = input("Describe what you built (technologies, outcomes, metrics): ").strip()
        profile.setdefault("projects", []).append({
            "name": name,
            "raw_context": raw_context,
            "framings": {},
        })
        print(f"Added project: {name}")

    elif choice == "2":
        category = input("Skill category (e.g., cloud, ai_ml, programming): ").strip()
        skill = input("Skill name: ").strip()
        profile.setdefault("skills", {}).setdefault(category, []).append(skill)
        print(f"Added skill: {skill} under {category}")

    elif choice == "3":
        name = input("Certification/training name: ").strip()
        is_cert = input("Is this a certification (y) or training (n)? ").strip().lower()
        if is_cert == "y":
            issuer = input("Issuer: ").strip()
            status = input("Status (Active/Expired): ").strip()
            profile.setdefault("certifications", []).append({
                "name": name, "issuer": issuer, "status": status,
            })
        else:
            profile.setdefault("training", []).append(name)
        print(f"Added: {name}")

    with open(path, "w") as f:
        yaml.dump(profile, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print("profile.yaml updated.\n")


if __name__ == "__main__":
    main()
