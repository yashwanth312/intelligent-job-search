"""Verify which companies have valid Lever and Ashby job boards."""
import asyncio
import aiohttp

LEVER_API = "https://api.lever.co/v0/postings"
ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board"

# Known H-1B sponsoring tech companies — guess their Lever/Ashby tokens
LEVER_CANDIDATES = [
    # Big Tech
    ("netflix", "Netflix"), ("github", "GitHub"),
    ("shopify", "Shopify"), ("atlassian", "Atlassian"),
    ("palantir", "Palantir"), ("snap", "Snap"),
    ("spotify", "Spotify"), ("twitter", "Twitter"),
    ("bytedance", "ByteDance"), ("tiktok", "TikTok"),
    # AI / ML
    ("anthropic", "Anthropic"), ("openai", "OpenAI"),
    ("cohere", "Cohere"), ("scaleai", "Scale AI"),
    ("scale", "Scale AI"), ("huggingface", "Hugging Face"),
    ("anyscale", "Anyscale"), ("perplexity", "Perplexity"),
    ("mistral", "Mistral AI"), ("adept", "Adept AI"),
    ("inflection", "Inflection AI"), ("runway", "Runway"),
    ("replicate", "Replicate"), ("together", "Together AI"),
    ("modal", "Modal"), ("wandb", "Weights & Biases"),
    ("deepmind", "DeepMind"), ("midjourney", "Midjourney"),
    ("character", "Character AI"),
    # Cloud / Infra
    ("cloudflare", "Cloudflare"), ("datadog", "Datadog"),
    ("hashicorp", "HashiCorp"), ("elastic", "Elastic"),
    ("mongodb", "MongoDB"), ("snowflake", "Snowflake"),
    ("confluent", "Confluent"), ("databricks", "Databricks"),
    ("vercel", "Vercel"), ("netlify", "Netlify"),
    ("supabase", "Supabase"), ("neon", "Neon"),
    ("render", "Render"), ("fly", "Fly.io"),
    ("pulumi", "Pulumi"), ("temporal", "Temporal"),
    ("coreweave", "CoreWeave"), ("lambda", "Lambda"),
    ("aiven", "Aiven"), ("clickhouse", "ClickHouse"),
    ("planetscale", "PlanetScale"), ("timescale", "Timescale"),
    ("cockroachlabs", "Cockroach Labs"),
    ("fivetran", "Fivetran"), ("dbt-labs", "dbt Labs"),
    ("airbyte", "Airbyte"), ("prefect", "Prefect"),
    ("redpanda", "Redpanda"),
    # Security
    ("crowdstrike", "CrowdStrike"), ("paloaltonetworks", "Palo Alto Networks"),
    ("snyk", "Snyk"), ("sentinelone", "SentinelOne"),
    ("zscaler", "Zscaler"), ("fortinet", "Fortinet"),
    ("okta", "Okta"), ("wiz", "Wiz"),
    ("orca-security", "Orca Security"), ("chainguard", "Chainguard"),
    ("aqua-security", "Aqua Security"), ("sysdig", "Sysdig"),
    ("abnormal-security", "Abnormal Security"),
    ("huntress", "Huntress"), ("vanta", "Vanta"),
    ("drata", "Drata"), ("tailscale", "Tailscale"),
    ("1password", "1Password"), ("bitwarden", "Bitwarden"),
    ("lacework", "Lacework"), ("semgrep", "Semgrep"),
    # DevOps / Platform
    ("gitlab", "GitLab"), ("circleci", "CircleCI"),
    ("harness", "Harness"), ("launchdarkly", "LaunchDarkly"),
    ("newrelic", "New Relic"), ("pagerduty", "PagerDuty"),
    ("buildkite", "Buildkite"), ("env0", "env0"),
    ("spacelift", "Spacelift"),
    # Fintech / SaaS
    ("stripe", "Stripe"), ("plaid", "Plaid"),
    ("brex", "Brex"), ("ramp", "Ramp"),
    ("robinhood", "Robinhood"), ("coinbase", "Coinbase"),
    ("ripple", "Ripple"), ("figma", "Figma"),
    ("notion", "Notion"), ("discord", "Discord"),
    ("reddit", "Reddit"), ("gusto", "Gusto"),
    ("squarespace", "Squarespace"), ("instacart", "Instacart"),
    ("grammarly", "Grammarly"), ("duolingo", "Duolingo"),
    ("hubspot", "HubSpot"), ("twilio", "Twilio"),
    ("block", "Block"), ("chime", "Chime"),
    ("sofi", "SoFi"), ("nerdwallet", "NerdWallet"),
    # More tech
    ("airtable", "Airtable"), ("asana", "Asana"),
    ("canva", "Canva"), ("miro", "Miro"),
    ("webflow", "Webflow"), ("retool", "Retool"),
    ("linear", "Linear"), ("postman", "Postman"),
    ("flexport", "Flexport"), ("navan", "Navan"),
    ("rippling", "Rippling"), ("lattice", "Lattice"),
    ("samsara", "Samsara"), ("toast", "Toast"),
    ("benchling", "Benchling"), ("loom", "Loom"),
    ("mapbox", "Mapbox"), ("sourcegraph", "Sourcegraph"),
    ("grafana", "Grafana"), ("fastly", "Fastly"),
    ("kong", "Kong"), ("ngrok", "ngrok"),
    ("teleport", "Teleport"),
]

ASHBY_CANDIDATES = [
    # Many modern startups use Ashby
    ("anthropic", "Anthropic"), ("openai", "OpenAI"),
    ("vercel", "Vercel"), ("linear", "Linear"),
    ("ramp", "Ramp"), ("notion", "Notion"),
    ("figma", "Figma"), ("retool", "Retool"),
    ("supabase", "Supabase"), ("neon", "Neon"),
    ("render", "Render"), ("fly", "Fly.io"),
    ("temporal", "Temporal"), ("modal", "Modal"),
    ("replicate", "Replicate"), ("together", "Together AI"),
    ("runway", "Runway"), ("midjourney", "Midjourney"),
    ("perplexity", "Perplexity"), ("cohere", "Cohere"),
    ("snyk", "Snyk"), ("vanta", "Vanta"),
    ("drata", "Drata"), ("chainguard", "Chainguard"),
    ("tailscale", "Tailscale"), ("ngrok", "ngrok"),
    ("postman", "Postman"), ("webflow", "Webflow"),
    ("sourcegraph", "Sourcegraph"), ("pulumi", "Pulumi"),
    ("prefect", "Prefect"), ("airbyte", "Airbyte"),
    ("hasura", "Hasura"), ("planetscale", "PlanetScale"),
    ("cockroach-labs", "Cockroach Labs"),
    ("redpanda", "Redpanda"), ("materialize", "Materialize"),
    ("buildkite", "Buildkite"), ("semgrep", "Semgrep"),
    ("lacework", "Lacework"), ("wandb", "Weights & Biases"),
    ("coreweave", "CoreWeave"), ("lambda", "Lambda"),
    ("grammarly", "Grammarly"), ("rippling", "Rippling"),
    ("loom", "Loom"), ("airtable", "Airtable"),
    ("canva", "Canva"), ("miro", "Miro"),
    ("benchling", "Benchling"), ("lattice", "Lattice"),
    ("watershed", "Watershed"), ("calm", "Calm"),
    ("anyscale", "Anyscale"), ("labelbox", "Labelbox"),
    ("starburst", "Starburst"), ("clickhouse", "ClickHouse"),
]


async def check_lever(session, token, name):
    url = f"{LEVER_API}/{token}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, list):
                    return (token, name, len(data))
    except Exception:
        pass
    return None


async def check_ashby(session, token, name):
    url = f"{ASHBY_API}/{token}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                count = len(data.get("jobs", []))
                return (token, name, count)
    except Exception:
        pass
    return None


async def main():
    # Deduplicate
    lever_unique = list({t: (t, n) for t, n in LEVER_CANDIDATES}.values())
    ashby_unique = list({t: (t, n) for t, n in ASHBY_CANDIDATES}.values())

    print(f"Testing {len(lever_unique)} Lever tokens...")
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*[check_lever(session, t, n) for t, n in lever_unique])
    lever_valid = sorted([r for r in results if r and r[2] > 0], key=lambda x: x[2], reverse=True)

    print(f"\nVALID Lever boards: {len(lever_valid)}")
    print(f"\n{'Company':<30} {'Token':<25} {'Jobs':>6}")
    print("-" * 63)
    for token, name, count in lever_valid:
        print(f"{name:<30} {token:<25} {count:>6}")

    print(f"\n\nTesting {len(ashby_unique)} Ashby tokens...")
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*[check_ashby(session, t, n) for t, n in ashby_unique])
    ashby_valid = sorted([r for r in results if r and r[2] > 0], key=lambda x: x[2], reverse=True)

    print(f"\nVALID Ashby boards: {len(ashby_valid)}")
    print(f"\n{'Company':<30} {'Token':<25} {'Jobs':>6}")
    print("-" * 63)
    for token, name, count in ashby_valid:
        print(f"{name:<30} {token:<25} {count:>6}")

    # Output YAML
    print("\n\n# === YAML ===\n")
    print("lever:")
    for token, name, count in lever_valid:
        print(f"  - token: {token}")
        print(f"    name: {name}")
    print("\nashby:")
    for token, name, count in ashby_valid:
        print(f"  - token: {token}")
        print(f"    name: {name}")


if __name__ == "__main__":
    asyncio.run(main())
