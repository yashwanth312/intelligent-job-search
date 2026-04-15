# Intelligent Job Search — Design Spec

**Date:** 2026-04-15
**Author:** Yashwanth Medisetti + Claude
**Status:** Approved
**Project:** `intelligent_job_search/`

---

## Problem Statement

The current job search automation (`job_search_automation/`) has fundamental limitations:

1. **Limited sources** — Only LinkedIn and Indeed (ZipRecruiter broken). Most job seekers use these, meaning 100+ applicants per listing within an hour.
2. **Weak screening** — Groq `llama-3.1-8b-instant` produces ~50% accuracy. Lets through 5+ year experience jobs, and there's zero visibility into what good jobs the regex filter incorrectly kills.
3. **No resume automation** — User manually copies each JD into Claude, generates resume + cover letter, downloads PDFs. Takes ~2 hours/day for ~15-20 applications.
4. **Narrow targeting** — Only searches DevOps/Cloud/Security titles. Misses the AI infrastructure intersection where the user's skills are most differentiated.
5. **No feedback loop** — No tracking of which sources, resume angles, or screening scores produce callbacks.

## User Profile

**Yashwanth Medisetti** — MS in Computer and Information Systems with specialization in Cyber Forensics and Security (GPA: 4.0), Illinois Institute of Technology, Chicago. Currently on F1 OPT, STEM-extendable through June 2028; sponsorship needed only after that.

**Core strength:** The intersection of Cloud/DevOps + Security + AI. Not a pure DevOps person, not a pure AI person — someone who deploys and secures AI systems in production.

**Experience:**
- Junior Security/DevOps Engineer at KV Bits (June 2024–present): Zero-trust password vault, IAM (AWS Cognito), CI/CD pipeline (40% velocity increase), AWS infrastructure with Terraform (90% less manual setup), monitoring dashboards (15% cost reduction), Task Tracker (full-stack: React 18 + TypeScript + FastAPI + PostgreSQL + JWT + RBAC + email notifications, built entirely with Claude Code)
- Software Developer Intern at Texas Instruments (Jan–July 2023): Frontend module redesign for QRE dashboards, legacy migration with trade-off analysis, Spring Boot backend, RESTful APIs, $75K savings, AI chatbot hackathon
- Security Training Associate at Walkover University (May 2021–July 2022): Trained 150+ students, founded CloudShare (200+ member community)

**Projects:**
- DiaSense AI — TensorFlow/Keras neural network (78% accuracy), Docker (650+ pulls), K8s/EKS deployment, CI/CD, HPA for 2500 concurrent users
- TerraSecure — Terraform IaC for AWS (VPCs, EC2, security groups), multi-VPC network architecture
- VibeBox — Web3 + IoT: Blockchain payments (Solidity, MetaMask, Chainlink on Base Sepolia), NFC access, smart plug/speaker control, React + Flask
- OSINT Tool — Flask-based multi-platform social media intelligence (Instagram, Twitter, Reddit, YouTube)
- Task Tracker (KV Bits) — Full-stack internal tool with RBAC, task templates, email notifications, admin dashboard
- Central Saffron Valley — Restaurant website redesign (Next.js 14, TypeScript, Tailwind v4)
- Intelligent Job Search (this project) — AI-powered multi-agent pipeline, portfolio piece
- 20+ DevOps/Cloud repos — Ansible K8s cluster automation, Terraform infra, Jenkins pipelines, MLOps, Azure deployments
- IEEE Published Research — Facial biometrics door unlocking system (98.43% accuracy)

**Certifications:**
- CompTIA Security+ CE (active, expires Feb 2028)
- Red Hat Certified System Administrator — RHCSA (active, expires Oct 2026)
- Google Cloud Associate Cloud Engineer (expired Apr 2025)
- Red Hat Certified Specialist in Containers & Kubernetes (expired May 2024)

**Training:** Amazon EKS, Ansible (RedHat RH294 + expert sessions), Azure, Docker, GCP (Workshop + project + Compute Engine), OpenShift (RedHat DO101), DevOps Assembly Lines, Hybrid Multi Cloud Computing, MLOps, MongoDB, Git/GitHub, PAM Linux Advanced Security, Coursera Cloud Computing, AI Workshop, Augmented Reality

**Skills (derived from projects + experience):**
- Cloud: AWS (EC2, S3, Lambda, EKS, CloudFormation, VPC, GuardDuty, WAF, Cognito), Azure, GCP
- Containers: Docker, Kubernetes, Helm, Containerd
- IaC: Terraform, Ansible, CloudFormation, Packer
- CI/CD: Jenkins, GitHub Actions, GitOps
- Security: Splunk, Nessus, Burp Suite, Metasploit, Nmap, Wireshark, ELK Stack, SIEM, Firewalls
- Frameworks: MITRE ATT&CK, NIST, ISO 27001, Zero Trust
- Programming: Python, JavaScript/TypeScript, Golang, Bash, PowerShell, Solidity, Java (Spring Boot), Dart
- Frontend: React, Next.js, Tailwind CSS, Vite
- Backend: FastAPI, Flask, Spring Boot, Node.js
- Databases: PostgreSQL, Supabase, SQLite, NoSQL, MongoDB
- ML/AI: TensorFlow, Keras, OpenCV, LLM integration, Claude Code agents/skills
- Web3: Solidity, MetaMask, Chainlink, Base Sepolia
- IoT: NFC, smart plugs, Bluetooth integration
- Observability: Prometheus, Grafana, Datadog, CloudWatch

---

## Solution: Intelligent Job Search Platform

A full rebuild with six integrated components, a tiered source strategy, AI-powered screening and resume generation, full audit visibility, and a feedback loop that improves the system over time.

### Target Role Strategy

Position at the intersection of Cloud/DevOps + Security + AI. Not abandoning existing experience — evolving it into a higher-demand niche where fewer people compete.

**Search titles:**

```
# Cloud / Infrastructure
Cloud Engineer, Cloud Infrastructure Engineer

# DevOps / SRE / Platform
DevOps Engineer, SRE, Platform Engineer, Cloud DevOps Engineer

# Security
Security Engineer, Cloud Security Engineer, DevSecOps Engineer,
Security Automation Engineer, Security Analyst

# AI Intersection
MLOps Engineer, AI Infrastructure Engineer, AI Platform Engineer,
AI Security Engineer, ML Platform Engineer, AI DevOps Engineer

# All with Junior/Associate prefixes where appropriate
```

**Search locations:** Chicago IL, New York NY, Seattle WA, Austin TX, Boston MA, Denver CO, Philadelphia PA, Washington DC, Remote

---

## Architecture

```
                        +-------------------+
                        |   Profile Vault   |
                        |   (YAML - you)    |
                        +--------+----------+
                                 |
       +-------------------------+----------------------------+
       |                         |                            |
       v                         v                            v
+----------------+   +-----------------------+   +--------------------+
| Multi-Source   |   |  Screening Engine     |   | Resume/CL Engine   |
| Scraper        |-->|  Stage 1: Regex       |   | (Claude CLI)       |
| (pluggable)    |   |  Stage 2: Claude CLI  |   |                    |
+----------------+   +-----------+-----------+   +---------+----------+
                                 |                          |
                     +-----------v-----------+   +----------v----------+
                     |   Google Sheets       |   |   Google Drive      |
                     |   (3 tabs)            |   |   (PDFs by company) |
                     +-----------+-----------+   +---------------------+
                                 |
                     User: Apply / Skip
                                 |
                     +-----------v-----------+
                     |   Feedback Loop       |
                     |   (SQLite)            |
                     +-----------------------+
```

### Component Summary

| Component | Job | Key Tech |
|-----------|-----|----------|
| Profile Vault | Structured knowledge base about the user | YAML, version-controlled |
| Multi-Source Scraper | Cast widest net, prioritize goldmine sources | python-jobspy + Greenhouse/Lever/Ashby APIs + HN/Wellfound/BuiltIn |
| Screening Engine | Kill bad fits transparently | Stage 1: regex (free, fast) -> Stage 2: Claude CLI (precise, profile-aware) |
| Google Sheets | Single UI for review, applications, visibility | gspread, 3 tabs in a NEW spreadsheet |
| Resume/CL Engine | Craft honest, tailored materials | Claude CLI + weasyprint PDFs, uploaded to Google Drive |
| Feedback Loop | Learn what works over time | SQLite tracking, periodic reports, user-approved tuning |

---

## Component 1: Profile Vault

A structured YAML knowledge base capturing every angle of the user's experience. The foundation for both screening and resume generation.

**File:** `profile.yaml`

**Structure:**

```yaml
personal:
  name: "Yashwanth Medisetti"
  email: "yashwanthsaikrishna@gmail.com"
  phone: "+1 (630) 276 8408"
  location: "Chicago, IL (Open to Relocation)"
  visa: "F1 OPT, STEM-extendable through June 2028. Sponsorship needed only after that."
  linkedin: "LinkedIn - Yashwanth Medisetti"

education:
  - school: "Illinois Institute of Technology, Chicago, IL"
    degree: "MS, Computer and Information Systems (Cyber Forensics and Security)"
    gpa: "4.0"
    graduation: "May 2025"
  - school: "Maulana Azad National Institute of Technology (NIT), Bhopal, India"
    degree: "B.Tech, Electrical Engineering"
    gpa: "3.45"
    graduation: "June 2023"

experiences:
  - company: "KV Bits"
    location: "Chicago, IL"
    period: "June 2024 - Present"
    framings:
      security:
        title: "Junior Security Engineer"
        bullets:
          - "Developed and deployed a zero-trust internal password vault and IAM system, providing secure credential management for a 20+ member team."
          - "Built a secure authentication layer using AWS Cognito, integrating client-side encryption and RBAC to enforce password policies and Least Privilege access."
          - "Hardened the digital infrastructure by configuring secure DNS, managing server administration, and implementing email security protocols (SPF/DKIM)."
          - "Maintained the company's security posture by operating a threat monitoring workflow based on SIEM principles and performing regular vulnerability scans."
      devops:
        title: "Junior DevOps Engineer"
        bullets:
          - "Designed and implemented a CI/CD pipeline for internal business applications, enabling automated builds, testing, and deployments which increased development team velocity by 40%."
          - "Led the end-to-end build-out of the company's digital infrastructure of the U.S. branch on AWS, automating the provisioning of network and server resources using Terraform, resulting in a 90% reduction in manual setup time."
          - "Engineered and deployed a high-availability internal password vault solution for 50 employees, managing the underlying database, application servers, and infrastructure reliability."
          - "Creating custom dashboards to monitor system health, performance, and AWS cloud costs, which led to a 15% reduction in monthly spend through resource optimization."
      ai_infrastructure:
        title: "Junior Infrastructure Engineer"
        bullets: []  # Generated dynamically from raw_context by the tailoring engine
    raw_context: |
      Built the company's US infrastructure from scratch. Password vault (zero-trust),
      CI/CD pipelines, AWS setup with Terraform, DNS/email security (SPF/DKIM),
      monitoring dashboards, SIEM-based threat monitoring, vulnerability scanning.
      Also built Task Tracker: full-stack internal tool (React 18 + TypeScript + 
      FastAPI + PostgreSQL + JWT + RBAC + task templates + email via Resend + admin
      dashboard). Deployed on Render/Vercel/Neon. Built entirely with Claude Code
      using skills and agentic framework. The fastest full-stack app ever shipped.
      Team size: 20-50 people.
      Technologies: AWS (Cognito, EC2, S3, EKS), Terraform, Jenkins, GitHub Actions,
      Docker, React, Next.js, TypeScript, FastAPI, PostgreSQL, Supabase, Resend.
      Metrics: 40% faster deployments, 90% less manual setup, 15% cost reduction.

  - company: "Texas Instruments"
    location: "Bangalore, India"
    period: "Jan 2023 - July 2023"
    framings:
      software_developer:
        title: "Software Developer Intern"
        bullets:
          - "Reduced third-party dependency risks and saved $75,000 in annual licensing costs by replacing unstable vendor tools with secure, in-house solutions built using RESTful APIs."
          - "Strengthened application security by identifying and resolving over 50 frontend and backend synchronization bugs, improving data integrity and system performance for 100+ internal users."
          - "Collaborated with Quality Assurance to troubleshoot critical production issues, authoring 20+ pages of technical documentation for security and system processes."
      devops:
        title: "Software Developer Intern"
        bullets:
          - "Developed and maintained over 10 production-level RESTful APIs, contributing to a microservices architecture that improved system performance and reliability for 100+ internal users."
          - "Reduced operational risk and saved $75,000 annually by engineering custom modules to replace unstable third-party dependencies, directly enhancing overall system stability."
          - "Collaborated with cross-functional teams (Quality Assurance, Product Management) to troubleshoot critical production issues and authored 20+ pages of technical documentation."
    raw_context: |
      Solely responsible for redesigning the frontend module that provided dashboard
      insights to Quality and Reliability Engineers (QREs). The existing module was
      legacy and lacked required functionality. Researched alternatives, built 
      trade-off documents (pros/cons), convinced management, and implemented the
      migration. Had to understand existing module, find alternatives in newer version,
      maintain existing functionality while allowing room for expansion. Required
      backend work in Spring Boot. Successfully completed the migration.
      Also participated in internal hackathon: built an AI chatbot for employees to
      discover different projects inside TI — an internal dictionary so people don't
      have to reach out directly for explanations.
      Technologies: Spring Boot, RESTful APIs, frontend frameworks, microservices.
      Metrics: $75K annual savings, 50+ bugs resolved, 100+ internal users, 10+ APIs.

  - company: "Walkover University"
    location: "Indore, India"
    period: "May 2021 - July 2022"
    framings:
      security:
        title: "Security Training Associate"
        bullets:
          - "Delivered comprehensive security training programs for 150+ global students, covering security architectures and frameworks, with a focus on anomaly detection, incident response, and risk mitigation strategies."
          - "Founded CloudShare, a 200+ member global community, to democratize cloud security education; curated workshops on secure CI/CD pipeline design, containerization best practices, and DevSecOps principles."
      devops:
        title: "Cloud Automation Trainer"
        bullets:
          - "Trained 150+ students on core DevOps principles, cloud architecture, and containerization, focusing on building scalable infrastructure and efficient CI/CD workflows."
          - "Designed 12+ hands-on labs covering Kubernetes deployments, Infrastructure as Code with Terraform, and implementing observability stacks with Prometheus and Grafana."
    raw_context: |
      Delivered cloud and security training to 150+ global students. Founded 
      CloudShare community (200+ members). Created workshops on CI/CD, 
      containerization, DevSecOps, Kubernetes, Terraform, Prometheus, Grafana.
      Focus areas: security architectures, anomaly detection, incident response,
      risk mitigation, observability.

projects:
  - name: "DiaSense AI"
    raw_context: |
      LLM-based / ML-based diabetes detection application. Neural network with
      TensorFlow/Keras (8 neurons input, 3 hidden layers, 78% accuracy, RELU + 
      SIGMOID activations, Adam optimizer). Containerized with custom Docker image
      (650+ downloads on DockerHub: yashwanth3/flask-keras:v2). Deployed on AWS EKS
      with CI/CD via Jenkins + GitHub Actions (automated build, container scanning,
      deployment to K8s cluster). Load balancing and horizontal pod autoscaling for
      2500 concurrent users. CentOS-based container with Python 3.
    framings:
      healthcare:
        bullets:
          - "Engineered the security architecture for a Large Language Model application to ensure secure handling of sensitive health data, making it resistant to web application security attacks."
          - "Hardened the application's security posture by containerizing it with a custom Docker image (650+ downloads on DockerHub), ensuring strict service isolation within a microservices architecture."
          - "Orchestrated a highly available and fault-tolerant deployment on AWS EKS, implementing robust load balancing and auto-scaling to ensure service uptime and resilience for up to 2,500 concurrent users."
      devops:
        bullets:
          - "Containerized a Python-based LLM application using a custom Docker image (650+ downloads) and orchestrated a highly available, fault-tolerant deployment on AWS EKS."
          - "Implemented a complete CI/CD pipeline using Jenkins and GitHub Actions that automated the build, container scanning, and deployment process to the Kubernetes cluster."
          - "Implemented robust load balancing and horizontal pod autoscaling to ensure service uptime and resilience, successfully handling up to 2,500 concurrent user sessions."
      ai_ml:
        bullets:
          - "Built and trained a neural network (TensorFlow/Keras) achieving 78% accuracy for diabetes prediction, using RELU/SIGMOID activations and Adam optimizer."
          - "Deployed the ML model as a production Flask API, containerized with Docker (650+ downloads) and orchestrated on AWS EKS with auto-scaling for 2500 concurrent users."

  - name: "TerraSecure"
    raw_context: |
      Automated cloud infrastructure provisioning using Terraform (IaC). Manages
      VPCs, EC2 instances, and security groups. Designed segmented network 
      architecture with public/private VPCs for data isolation, controlled access,
      and minimal attack surface.
    framings:
      security:
        bullets:
          - "Automated cloud infrastructure provisioning using Infrastructure as Code (IaC - Terraform), to manage VPCs, EC2 instances, and security groups, significantly reducing manual configuration time."
          - "Designed a segmented network architecture with public/private VPCs, ensuring data isolation, controlled access, and minimal attack surface."
      devops:
        bullets:
          - "Automated the provisioning and management of a secure AWS cloud infrastructure using Terraform, implementing Infrastructure as Code (IaC) to reduce manual configuration and deployment times."
          - "Designed a multi-VPC network with public and private subnets to ensure network segmentation and isolate database resources from public-facing web applications."

  - name: "VibeBox"
    raw_context: |
      Interactive ambient jukebox combining Web3 + IoT. Blockchain payments via
      MetaMask on Base Sepolia test network. Chainlink Functions for triggering
      API calls on transaction confirmation. Solidity smart contract for transaction
      validation. NFC-enabled access through embedded chips. Smart plug control for
      lighting, Bluetooth speaker connectivity for audio. React frontend, Flask
      backend, Web3 wallet integration. Central hub coordinating IoT device operations.
    framings:
      web3:
        bullets:
          - "Built a decentralized payment system using Solidity smart contracts on Base Sepolia, with MetaMask wallet integration and Chainlink Functions for blockchain-to-hardware communication."
          - "Engineered NFC-enabled access control and IoT device orchestration (smart plugs, Bluetooth speakers) through a Flask backend coordinating real-time environmental responses."
      fullstack:
        bullets:
          - "Designed and built a full-stack IoT platform (React + Flask) integrating blockchain payments, NFC authentication, and real-time smart device control for commercial environments."

  - name: "OSINT Tool"
    raw_context: |
      Flask-based web application for Open Source Intelligence. Retrieves and 
      analyzes profile data from Instagram, Twitter, Reddit, YouTube through a
      unified interface. Features OAuth authentication, API key management,
      data visualization of retrieved metrics. Python 3.10+.
    framings:
      security:
        bullets:
          - "Developed an OSINT web application for multi-platform social media intelligence gathering (Instagram, Twitter, Reddit, YouTube), featuring OAuth integration and automated data visualization."

  - name: "Task Tracker"
    raw_context: |
      Full-stack internal tool for KV Bits. Manager delegates tasks to employees,
      tracks progress. RBAC with multiple roles and permissions (create, update,
      delegate, delete based on role). Task templates for different departments
      (HR: timesheets, onboarding; Client Manager: vendor empanelment, legal docs).
      Task creation in 5-10 seconds via templates. Email integrated (Resend) for
      automatic notifications on new/updated tasks. Admin dashboard for high-level
      summary. JWT authentication (60-min expiry). Status flow: pending -> 
      in_progress -> completed.
      Tech: React 18, TypeScript, Vite, Tailwind CSS, TanStack Query v5,
      React Hook Form + Zod validation, Axios. Backend: FastAPI, SQLAlchemy 2 (async),
      Alembic migrations, PostgreSQL via asyncpg, python-jose + bcrypt for auth,
      fastapi-mail for SMTP. Deployed: Render (backend), Vercel (frontend), Neon (DB).
      Built ENTIRELY with Claude Code using skills and agentic framework.
      The fastest full-stack app ever shipped.
    framings:
      fullstack:
        bullets:
          - "Architected and shipped a full-stack task management system (React 18 + TypeScript + FastAPI + PostgreSQL) with RBAC, task templates, email notifications, and an admin dashboard."
          - "Implemented role-based access control with JWT authentication, enabling granular permissions for task creation, delegation, and status management across departments."
          - "Built the entire application using AI-assisted development (Claude Code with agentic framework), demonstrating proficiency in AI-powered software engineering workflows."
      ai_engineering:
        bullets:
          - "Shipped a production full-stack application entirely using AI-assisted development (Claude Code agents and skills), achieving rapid delivery while maintaining code quality."
          - "Coordinated AI agents for end-to-end development: architecture design, component implementation, API development, database migrations, authentication, and deployment configuration."

  - name: "Intelligent Job Search"
    raw_context: |
      AI-powered multi-agent job search platform. Multi-source scraping (Greenhouse
      API, Lever API, LinkedIn, Indeed, HN Who's Hiring, Wellfound, BuiltIn).
      Two-stage screening: regex fast filter + Claude CLI precision screen with
      profile-aware evaluation. Automated resume and cover letter generation using
      Claude Code CLI with structured profile vault. Google Sheets as single UI.
      Google Drive for PDF storage. SQLite feedback loop tracking source quality,
      screening accuracy, and resume angle effectiveness. Batch processing,
      connection pooling, incremental scraping. Python, asyncio, aiohttp.
    framings:
      ai_engineering:
        bullets:
          - "Built an AI-powered job search platform with multi-agent architecture: LLM-based screening, automated resume tailoring, and feedback-driven optimization."
          - "Implemented multi-source job scraping (8+ sources including direct ATS APIs), two-stage AI screening, and automated document generation using Claude Code CLI."

  - name: "Face Recognition Door Lock (IEEE Published)"
    raw_context: |
      IEEE International 2023 SCEECS published research. Biometric authentication
      for physical access control. Prototype achieving 98.43% accuracy in controlled
      tests. Integrates AI, IoT, and cybersecurity with email alerting. Replaces
      traditional locks with facial biometrics.

  - name: "Various DevOps/Cloud Projects"
    raw_context: |
      20+ GitHub repos demonstrating breadth:
      - Ansible: K8s cluster automation (master + worker node roles), WordPress+MySQL,
        EC2 provisioning, expert-level playbooks
      - Terraform: Multiple cloud infra projects (VPCs, EC2, security groups), HCL
      - Kubernetes: K8s webapp deployment, EKS setup
      - Docker: Containerization projects, Dockerfiles, docker-compose (Joomla+MySQL)
      - Jenkins: CI/CD pipelines, Jenkins-Docker automation
      - MLOps: ML deployment pipelines
      - Azure: App Service deployment
      - LVM automation scripts (Linux storage management)
      - OpenShift projects
      - Flask/Python chatbots
      - ML models: Salary prediction, Mask-RCNN, Hough Lines detection, transfer learning

certifications:
  - name: "CompTIA Security+ CE"
    issuer: "CompTIA"
    status: "Active"
    expires: "Feb 2028"
  - name: "Red Hat Certified System Administrator (RHCSA)"
    issuer: "Red Hat"
    status: "Active"
    expires: "Oct 2026"
  - name: "Google Cloud Associate Cloud Engineer"
    issuer: "Google Cloud"
    status: "Expired"
    expires: "Apr 2025"
    note: "Skill still current, certification lapsed"
  - name: "Red Hat Certified Specialist in Containers and Kubernetes"
    issuer: "Red Hat"
    status: "Expired"
    expires: "May 2024"
    note: "Skill still current, certification lapsed"

training:
  - "Amazon EKS"
  - "Ansible - RedHat (RH294)"
  - "Ansible Expert Sessions"
  - "Azure Workshop"
  - "Docker Certification"
  - "GCP Workshop + Project Certificate"
  - "Google Compute Engine (Coursera)"
  - "Cloud Computing (Coursera)"
  - "OpenShift - RedHat (DO101)"
  - "DevOps Assembly Lines"
  - "Hybrid Multi Cloud Computing"
  - "MLOps Certificate"
  - "MongoDB Workshop"
  - "Git/GitHub Workshop"
  - "PAM Linux Advanced Security"
  - "AI Workshop"
  - "Augmented Reality (Coursera)"

skills:
  # Derived from actual projects and experience, not a word list
  cloud:
    - "AWS (EC2, S3, Lambda, EKS, CloudFormation, VPC, GuardDuty, WAF, Cognito)"
    - "Azure (App Service)"
    - "GCP (Compute Engine, certified ACE)"
  containers:
    - "Docker"
    - "Kubernetes (EKS, cluster automation)"
    - "Helm"
    - "Containerd"
    - "OpenShift"
  iac:
    - "Terraform"
    - "Ansible (RH294 certified)"
    - "CloudFormation"
    - "Packer"
  cicd:
    - "Jenkins"
    - "GitHub Actions"
    - "GitOps"
  security:
    - "Splunk"
    - "Nessus"
    - "Burp Suite"
    - "Metasploit"
    - "Nmap"
    - "Wireshark"
    - "ELK Stack"
    - "SIEM"
    - "Firewalls"
    - "IAM"
    - "Zero Trust"
    - "OSINT"
  frameworks:
    - "MITRE ATT&CK"
    - "NIST"
    - "ISO 27001"
    - "Cryptography"
  programming:
    - "Python"
    - "JavaScript/TypeScript"
    - "Golang"
    - "Bash"
    - "PowerShell"
    - "Solidity"
    - "Java (Spring Boot)"
    - "Dart (Flutter)"
  frontend:
    - "React 18"
    - "Next.js 14"
    - "Tailwind CSS"
    - "Vite"
    - "TanStack Query"
  backend:
    - "FastAPI"
    - "Flask"
    - "Spring Boot"
    - "Node.js"
  databases:
    - "PostgreSQL"
    - "Supabase"
    - "SQLite"
    - "MongoDB"
  ai_ml:
    - "TensorFlow"
    - "Keras"
    - "OpenCV"
    - "LLM integration"
    - "Claude Code (agents, skills, context management)"
    - "AI-assisted development"
  web3:
    - "Solidity"
    - "MetaMask"
    - "Chainlink Functions"
    - "Base Sepolia"
  iot:
    - "NFC"
    - "Smart plugs"
    - "Bluetooth integration"
  observability:
    - "Prometheus"
    - "Grafana"
    - "Datadog"
    - "CloudWatch"
    - "ELK Stack"
  networking:
    - "TCP/IP"
    - "TLS/SSL"
    - "DNS"
    - "Load Balancing"
    - "SSH"
    - "HTTP/HTTPS"
```

**Key design decisions:**

1. **`raw_context`** is the most important field. It's the honest, unpolished truth of what the user did. The tailoring engine reads raw_context + JD and generates NEW bullet framings that are truthful but optimally positioned. Not limited to pre-written bullets.

2. **`framings`** are pre-written versions already validated (from existing resumes). The engine uses these as starting points but can generate new ones from raw_context.

3. **The profile is a living document.** User updates it as skills evolve, new projects are built. `update_profile.py` provides a guided Q&A interface for adding new entries.

4. **Skills are derived from projects and experience**, not maintained as a standalone word list. The tailoring engine selects relevant skills based on JD requirements.

---

## Component 2: Multi-Source Scraper

### Tiered Source Strategy

**Tier 1 — The Goldmine (low competition, early access)**

Jobs appear here FIRST, often days before LinkedIn. Most applicants never check these directly.

| Source | Method | Details |
|--------|--------|---------|
| **Greenhouse API** | `GET boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | No auth required. Public JSON API. Maintain curated list of ~50-100 target companies (AI companies, known sponsors, target-city employers). Returns full JD, location, salary (with `pay_transparency` flag). |
| **Lever API** | `GET api.lever.co/v0/postings/{company}` | No auth required. Public JSON. Target mid-stage startups. |
| **Ashby API** | Public API | Growing adoption in AI startups. |

**Tier 2 — High-Quality Niche (moderate competition)**

| Source | Method | Details |
|--------|--------|---------|
| **HN "Who's Hiring"** | Algolia API (`hn.algolia.com/api/v1`) | No auth, no rate limits. 400-900 posts per monthly thread. Standard format: `Company \| Role \| Location \| Remote`. Deterministic regex parsing. |
| **Wellfound** | Custom scraper | 150K+ startup tech jobs. AI-heavy. |
| **BuiltIn** | Custom scraper | Strong in Chicago, Austin, Denver, NYC — target cities. |
| **YC Work at a Startup** | Custom scraper | YC companies, strong AI presence. |

**Tier 3 — Specialized (low volume, very targeted)**

| Source | Method | Details |
|--------|--------|---------|
| **ai-jobs.net** | Custom scraper | AI-specific roles. |
| **Dice** | Custom scraper | Tech-specific, less competition than LinkedIn. |
| **Hugging Face Jobs** | Custom scraper | LLM ecosystem. |
| **MLOps.Community** | Custom scraper | MLOps-specific. |
| **RemoteOK** | Public JSON API | Remote tech roles. |

**Tier 4 — Volume (high competition, still useful)**

| Source | Method | Details |
|--------|--------|---------|
| **LinkedIn** | `python-jobspy` | High competition but broadest coverage. |
| **Indeed** | `python-jobspy` | Good for non-tech companies hiring tech roles. |

**ZipRecruiter** — dropped entirely.

### Pluggable Adapter Pattern

Each source implements a common interface:

```python
class SourceAdapter:
    name: str
    def scrape(self, titles: list[str], locations: list[str]) -> list[RawJob]
```

**RawJob schema (Pydantic):**

```python
class RawJob(BaseModel):
    title: str
    company: str
    location: str
    description: str | None
    salary_min: int | None
    salary_max: int | None
    url: str
    source: str           # "greenhouse-anthropic", "hn-apr2026", "linkedin"
    scraped_at: datetime
    fingerprint: str      # f"{company.lower()}||{title.lower()}"
```

### Target Companies List

Maintained in `target_companies.yaml`:

```yaml
greenhouse:
  - token: anthropic
    name: Anthropic
  - token: openai
    name: OpenAI
  - token: datadog
    name: Datadog
  - token: cloudflare
    name: Cloudflare
  - token: crowdstrike
    name: CrowdStrike
  # ... ~50-100 companies

lever:
  - token: somecompany
    name: Some Company
  # ...
```

User can add/remove target companies at any time.

### Design Decisions

- All sources scraped in parallel via `asyncio.gather()` — not sequential
- Each adapter handles its own rate limiting and error handling
- If one source fails, pipeline continues with the rest (graceful degradation)
- New sources added by dropping a new adapter file into `sources/` directory
- Incremental scraping: check fingerprints against SQLite before screening (don't re-process known jobs)

---

## Component 3: Two-Stage Screening Engine

### Stage 1: Fast Filter (regex + rules)

Same logic as current system but with full audit logging.

**Filters applied (in order):**
1. Deduplication via fingerprint (`company||title`) — checked against SQLite
2. Title exclusion (senior, lead, director, VP, intern, contractor, etc.)
3. Title domain check — at least one domain keyword must match (cloud, devops, security, sre, platform, infrastructure, mlops, ai)
4. Description hard-stops (5+ years explicit, clearance, no sponsorship, US citizenship required)
5. Salary floor check ($70K)
6. Must-have keyword check (at least one of: aws, cloud, kubernetes, terraform, devops, security, etc.)
7. USA location filter
8. Empty description filter — if description is None/empty, reject (can't screen what doesn't exist)

**Audit logging:**
Every rejected job gets logged to SQLite `screening_audit` table:

```sql
CREATE TABLE screening_audit (
    id INTEGER PRIMARY KEY,
    job_fingerprint TEXT,
    company TEXT,
    title TEXT,
    source TEXT,
    stage TEXT,          -- "stage1_dedup", "stage1_title", "stage1_desc", "stage2_claude"
    verdict TEXT,        -- "REJECT", "PASS", "APPLY", "SKIP", "MAYBE"
    reason TEXT,         -- "title contains 'senior'", "description: 'TS/SCI clearance'"
    confidence INTEGER,  -- NULL for stage1, 1-5 for stage2
    run_date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Stage 2: Claude Precision Screen

Replaces Groq entirely. Uses Claude Code CLI (`claude -p`).

**Batching:** 10-15 JDs per invocation. Each invocation is independent (fresh context).

**Input:** Batch of JDs + user profile summary (extracted from profile.yaml).

**Output (structured JSON per job):**

```json
{
  "verdict": "APPLY",
  "confidence": 4,
  "reasoning": "Strong match: role requires AWS + K8s + CI/CD for ML workloads. 2+ years experience aligns. No sponsorship red flags.",
  "match_signals": ["EKS", "Terraform", "ML pipeline", "junior-friendly"],
  "risk_flags": ["mentions 'preferred: 3 years' but not required"],
  "suggested_angle": "AI Infrastructure - emphasize DiaSense EKS deployment + MLOps"
}
```

**Fields:**
- `verdict`: APPLY / SKIP / MAYBE
- `confidence`: 1-5 scale
- `reasoning`: human-readable explanation
- `match_signals`: what in the JD matched the user's profile
- `risk_flags`: concerns (soft experience reqs, vague sponsorship)
- `suggested_angle`: which resume framing works best — feeds into resume engine

**Profile-aware screening:** Unlike generic Groq screening, Claude checks against the user's specific profile. A job asking for "GCP experience preferred" gets boosted (user has ACE cert). A job at a known sponsor gets noted. A job requiring Golang gets flagged (user has it but it's not primary).

**What reaches the Daily tab:**
- APPLY (confidence 3+) — ready for material generation
- MAYBE — flagged for manual review
- SKIP — filtered out, reasoning in Audit tab

---

## Component 4: Google Sheets Integration

**NEW spreadsheet:** "Intelligent Job Search" (separate from existing tracker)
**NEW Drive folder:** "Intelligent Job Search Materials"

### Tab Structure

**Daily Tab (ephemeral — cleared each run):**

| Column | Content |
|--------|---------|
| Date Scraped | Today's date |
| Company | Company name |
| Job Title | Job title |
| Location | Job location |
| Source | Where it was found (greenhouse-anthropic, hn, linkedin, etc.) |
| Confidence | 1-5 screening score |
| AI Reasoning | One-line screening explanation |
| Suggested Angle | Recommended resume framing |
| Risk Flags | Concerns (experience, sponsorship) |
| Match Signals | Key JD-to-profile matches |
| Salary Range | If available |
| Apply Link | Direct application URL |
| Status | Dropdown: Apply / Skip / Review Later |
| Notes | User notes |

**Audit Tab (ephemeral — cleared each run):**

| Column | Content |
|--------|---------|
| Company | Company name |
| Job Title | Job title |
| Killed At | Stage + filter (e.g., "Stage 1: Title Exclusion") |
| Reason | Specific reason ("title contains 'senior'") |
| Source | Where it was found |
| Apply Link | URL (in case it was a false negative) |

**Applied Tab (persistent — grows over time):**

| Column | Content |
|--------|---------|
| Date Applied | When user applied |
| Company | Company name |
| Job Title | Job title |
| Location | Location |
| Resume Link | Google Drive link to tailored resume PDF |
| Cover Letter Link | Google Drive link to cover letter PDF |
| Apply Link | Application URL |
| Angle Used | Which resume framing was generated |
| Screen Confidence | Original screening score |
| Source | Where the job was found |
| Status | Dropdown: Ready to Apply / Applied / Phone Screen / Interview / Offer / Rejected / No Response |
| Days Waiting | Auto-calculated from date applied |
| Follow-up Date | 7 days after application |
| Follow-up Sent | Yes/No |
| Notes | User notes |

### Tab Lifecycle

1. `main.py` starts → saves yesterday's Daily + Audit data to SQLite → clears both tabs → writes fresh results
2. User reviews Daily tab, marks Apply/Skip
3. `generate_materials.py` → reads Apply rows, generates materials, moves to Applied tab with Drive links
4. Next day's `main.py` run → clears Daily + Audit again. Applied tab untouched.

**Important:** Before clearing, ALL data is persisted to SQLite. The feedback loop reads from SQLite, not Sheets. Sheets is purely a UI layer showing what's actionable right now.

### Duplicate Company Detection

If the user has already applied to Google this week and a new Google role appears in the Daily tab, the AI Reasoning column includes: "Note: Applied to Google for Cloud Engineer on Apr 10 — similar role?"

---

## Component 5: Resume/Cover Letter Engine

### Flow

```
User marks "Apply" in Daily tab
          |
          v
  python generate_materials.py
          |
          v
  For each Apply job:
    1. Read JD from SQLite (full description)
    2. Read profile.yaml
    3. Invoke Claude Code CLI (fresh invocation per job)
    4. Claude analyzes JD, selects best framings, generates content
    5. Validate output (all claims traceable to profile vault)
    6. Render to PDF via weasyprint (HTML template)
    7. Upload to Google Drive (company/date_role/)
    8. Update Applied tab with Drive links
          |
          v
  Google Drive: Intelligent Job Search Materials/
    google/
      2026-04-15_mlops-engineer/
        Yashwanth_Medisetti_Resume.pdf
        Yashwanth_Medisetti_Cover_Letter.pdf
        _metadata.json
```

### Claude CLI Invocation Strategy

**One fresh invocation per resume/cover letter pair.** No context accumulation across jobs. This ensures:
- Job #15 doesn't get influenced by jobs #1-14
- Full context budget available for each generation
- Consistent quality regardless of batch size

**What Claude receives per invocation:**
- Full profile.yaml content
- Single job description
- Screening metadata (suggested_angle, match_signals, risk_flags)
- Resume template structure (sections, formatting rules)
- Honesty constraints

**What Claude returns (structured JSON):**
```json
{
  "resume": {
    "summary": "...",
    "experience": [
      {
        "source": "kvbits",
        "framing_used": "ai_infrastructure",
        "title": "...",
        "bullets": ["...", "..."]
      }
    ],
    "projects": [...],
    "skills": {...},
    "certifications": [...]
  },
  "cover_letter": "...",
  "decisions": {
    "angle": "AI Infrastructure",
    "kvbits_framing": "ai_infrastructure",
    "ti_framing": "software_developer",
    "projects_included": ["DiaSense AI", "Intelligent Job Search"],
    "projects_excluded": {"VibeBox": "Web3/IoT not relevant to this JD"},
    "skills_reordered": "Cloud & AI first, Security second",
    "certs_highlighted": ["GCP ACE", "RHCSA"]
  }
}
```

### Honesty Guardrails

The prompt explicitly instructs:
- Only use experiences, projects, and skills from the profile vault
- Never fabricate metrics, titles, technologies, or company names
- May reframe and emphasize differently, but every claim must trace back to raw_context
- Never change job titles, dates, company names, or degree
- Allowed: summary rewriting, bullet emphasis changes, skill reordering, project selection

### Metadata Audit Trail

Every generated resume includes `_metadata.json`:
- Which profile entries were used
- How they were reframed
- Why certain projects were included/excluded
- Which certifications were highlighted
- Honesty check: all_claims_traceable flag

### PDF Generation

- HTML template matching the user's current resume style
- `weasyprint` for HTML → PDF conversion
- Professional filenames: `Yashwanth_Medisetti_Resume.pdf`
- Consistent formatting across all generated resumes

### Google Drive Organization

```
Intelligent Job Search Materials/
  google/
    2026-04-15_mlops-engineer/
      Yashwanth_Medisetti_Resume.pdf
      Yashwanth_Medisetti_Cover_Letter.pdf
      _metadata.json
    2026-04-12_ai-platform-engineer/
      ...
  anthropic/
    2026-04-15_ai-infrastructure-engineer/
      ...
```

Company-first structure. When applying on Google's career page, all Google materials are in one folder.

---

## Component 6: Feedback Loop

### Data Collection

When `main.py` runs, it saves yesterday's Daily + Audit data to SQLite before clearing. When the user updates the Applied tab status, `sync.py` (or a new `feedback_sync.py`) pulls outcomes into SQLite.

**Feedback table:**

```sql
CREATE TABLE feedback (
    id INTEGER PRIMARY KEY,
    job_fingerprint TEXT,
    company TEXT,
    title TEXT,
    source TEXT,           -- greenhouse-anthropic, hn, linkedin, etc.
    screen_confidence INTEGER,
    resume_angle TEXT,
    date_applied TEXT,
    outcome TEXT,          -- applied, phone_screen, interview, offer, rejected, no_response
    days_to_response INTEGER,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

### Feedback Report — `python feedback_report.py`

Generates analysis from SQLite data:

**Source quality:**
```
Source              | Applied | Callbacks | Rate
--------------------+---------+-----------+------
Greenhouse-direct   | 12      | 5         | 42%
HN Who's Hiring     | 8       | 3         | 38%
LinkedIn            | 25      | 2         | 8%
```

**Screening calibration:**
```
Confidence | Applied | Callbacks | Accuracy
-----------+---------+-----------+---------
5          | 10      | 6         | 60%
4          | 18      | 5         | 28%
3          | 20      | 2         | 10%
```

**Resume angle effectiveness:**
```
Angle              | Used | Callbacks | Rate
-------------------+------+-----------+------
AI Infrastructure  | 15   | 5         | 33%
Security           | 12   | 2         | 17%
DevOps             | 18   | 2         | 11%
```

**Recommendations (user-approved):**
```
1. Source: Drop Indeed - 0 callbacks from 47 applications
2. Screening: Raise threshold to confidence 4+
3. Angle: "AI Infrastructure" outperforming "DevOps" 3:1
4. Title: "MLOps Engineer" producing 0 results - consider removing

Accept recommendations? [y/n/selective]
```

The system never changes its own rules without user approval.

---

## Visibility & Control

### Terminal Run Summary

Every `main.py` run prints a detailed summary:
- Sources scraped (count per source, success/failure)
- Dedup count
- Stage 1 filter breakdown (how many killed per filter, with reasons)
- Stage 2 Claude screen breakdown (APPLY/MAYBE/SKIP counts by confidence)
- Total jobs written to Daily tab
- Any warnings or errors

### Google Sheets (the single UI)

- **Daily tab** — today's candidates with confidence scores, reasoning, risk flags
- **Audit tab** — everything that was filtered and exactly why
- **Applied tab** — application cockpit with resume/CL/apply links, status tracking

### Generation Metadata

`_metadata.json` alongside every PDF showing exactly what decisions were made and why.

### Control Mechanisms

| Action | How |
|--------|-----|
| See why a job was rejected | Check Audit tab or query screening_audit in SQLite |
| Override a screening decision | Flag it in Sheets, system learns |
| Change search titles | Edit config.py |
| Add/remove target companies | Edit target_companies.yaml |
| Adjust screening strictness | Change confidence threshold in config |
| See what went into a resume | Read _metadata.json |
| Check if system is helping | Run feedback_report.py |
| Stop a particular framing | Edit profile.yaml |
| Add new skills/projects | Update profile.yaml or run update_profile.py |

---

## Performance, Accuracy & Build Strategy

### AI Accuracy

1. **Fresh Claude CLI invocation per resume/CL pair** — no context accumulation, no cross-contamination between jobs
2. **Structured output enforcement** — every Claude prompt demands JSON matching a strict schema; output validated programmatically before use
3. **Prompt templates stored as files** (`prompts/screening.md`, `prompts/resume.md`, `prompts/cover_letter.md`) — version-controlled, testable, iterable without touching Python code
4. **Temperature control** — screening at temperature=0 for consistency; resume generation at low temperature for quality
5. **Output validation** — after Claude generates resume content, validate: all sections present, all claims trace to profile vault, correct length

### Performance

6. **Parallel scraping** — all sources via `asyncio.gather()`, not sequential. Greenhouse: 50 companies hit concurrently.
7. **Batch processing** — Stage 2 screening: 10-15 JDs per Claude call. Sheets writes: single `batch_update()`. Drive uploads: batched.
8. **Incremental scraping** — check fingerprints against SQLite before screening. Don't re-process known jobs.
9. **Connection pooling** — single `aiohttp.ClientSession` for all HTTP calls. Reuse Sheets/Drive clients.
10. **Progress bars** — Rich progress indicators for every long-running stage.

### Build Quality

11. **Context7 plugin** — pull current library docs before writing integration code (gspread, python-jobspy, weasyprint, Google Drive API, Greenhouse API)
12. **Fail-fast startup** — validate all config, credentials, APIs before the pipeline does any work. Clear error messages with fix instructions.
13. **Pydantic models** — strict schemas at all data boundaries: `RawJob`, `ScreenedJob`, `ProfileEntry`, `GeneratedMaterials`. Catches errors at boundaries, not deep inside logic.
14. **Graceful degradation** — one source failure doesn't kill the pipeline. Each adapter has its own error handling.
15. **Idempotent operations** — re-running is safe. Dedup catches duplicates. Generate skips already-generated materials unless forced.
16. **Structured logging** — Python `logging` module. INFO to terminal, DEBUG to `logs/run_YYYY-MM-DD.log`. Full troubleshooting detail in log files.
17. **Modular architecture** — each component is a standalone module with clean interfaces. Independently testable.

### Estimated Pipeline Runtime

| Stage | Current System | New System |
|-------|---------------|------------|
| Scraping (all sources) | 8-12 min (2 sources) | ~3-5 min (8+ sources, parallel) |
| Dedup + Stage 1 filter | ~1 min | <5 seconds |
| Stage 2 screen | ~2 min (Groq) | ~3-5 min (Claude CLI, batched) |
| Sheets write | ~3 sec | ~3 sec |
| **Total main.py** | **~12 min** | **~8-12 min** |
| Resume generation (15 jobs) | **2 hrs manual** | **~15-20 min automated** |
| Drive upload | N/A | ~1-2 min (batched) |
| **Total generate_materials.py** | **2 hours** | **~17-22 min** |

---

## Daily Workflow

1. **Run `python main.py`** (~8-12 min) — scrapes all sources, screens, writes to Daily + Audit tabs. Yesterday's data saved to SQLite and cleared from Sheets.
2. **Review Daily tab** (~10-15 min) — better jobs, confidence scores, reasoning visible. Check Audit tab if curious about what was filtered.
3. **Mark Apply/Skip** in Daily tab.
4. **Run `python generate_materials.py`** (~15-20 min automated) — generates tailored resume + cover letter per Apply job, uploads to Drive, moves to Applied tab with clickable links.
5. **Apply** — open Applied tab, click Resume Link to download, click Apply Link to open application page. Update status when done.
6. **Update outcomes** in Applied tab as they come in (Interview, Rejected, No Response).
7. **Run `python feedback_report.py`** weekly — see what's working, approve/reject system recommendations.

**From 2+ hours manual work to ~30 minutes of active time**, with significantly better job discovery and tailored materials.

---

## File Structure

```
intelligent_job_search/
  config.py                    # Titles, locations, thresholds, settings
  main.py                      # Pipeline: scrape -> filter -> screen -> Sheets
  generate_materials.py        # Resume + CL generation + Drive upload
  feedback_report.py           # Analyze outcomes, recommend adjustments
  feedback_sync.py             # Sync Applied tab outcomes to SQLite
  update_profile.py            # Guided Q&A to add new profile entries
  profile.yaml                 # The profile vault
  target_companies.yaml        # Greenhouse/Lever/Ashby company list
  requirements.txt             # Python dependencies
  .env                         # Secrets (API keys, credentials)
  sources/                     # Scraper adapters
    __init__.py
    base.py                    # SourceAdapter interface + RawJob schema
    greenhouse.py
    lever.py
    ashby.py
    linkedin_indeed.py         # python-jobspy wrapper
    hackernews.py
    wellfound.py
    builtin.py
    yc_startup.py
    dice.py
    remoteok.py
    ai_jobs.py
  screening/
    __init__.py
    stage1.py                  # Regex fast filter
    stage2.py                  # Claude CLI precision screen
  generation/
    __init__.py
    resume_engine.py           # Claude CLI resume generation
    cover_letter_engine.py     # Claude CLI cover letter generation
    pdf_renderer.py            # HTML template -> PDF via weasyprint
    drive_uploader.py          # Google Drive upload
  sheets/
    __init__.py
    client.py                  # Sheets connection + helpers
    daily.py                   # Daily tab operations
    audit.py                   # Audit tab operations
    applied.py                 # Applied tab operations
  models/
    __init__.py
    job.py                     # RawJob, ScreenedJob Pydantic models
    profile.py                 # Profile vault Pydantic models
    materials.py               # GeneratedMaterials model
  prompts/
    screening.md               # Screening prompt template
    resume.md                  # Resume generation prompt template
    cover_letter.md            # Cover letter prompt template
  templates/
    resume.html                # Resume PDF template (HTML/CSS)
  db/
    __init__.py
    database.py                # SQLite connection + migrations
    queries.py                 # Common queries
  logs/                        # Run logs (gitignored)
  output/                      # Local PDF copies (gitignored)
  docs/
    superpowers/
      specs/
        2026-04-15-intelligent-job-search-design.md  # This document
```

---

## Secrets and Configuration

### .env (gitignored)

```
GROQ_API_KEY=...              # Keep for potential fallback
GOOGLE_SHEETS_CREDS_FILE=credentials.json
GOOGLE_DRIVE_FOLDER_ID=...    # New Drive folder ID
YOUR_NAME=Yashwanth Medisetti
YOUR_EMAIL=yashwanthsaikrishna@gmail.com
YOUR_PHONE=+1 (630) 276 8408
```

### config.py

All tunable parameters:
- TARGET_TITLES list
- LOCATIONS list
- EXCLUDE_TITLE_KEYWORDS list
- EXCLUDE_DESC_PATTERNS list
- SALARY_FLOOR
- SCREENING_CONFIDENCE_THRESHOLD (default: 3)
- SCREENING_BATCH_SIZE (JDs per Claude CLI invocation, default: 10)
- SCRAPER_WORKERS (thread pool size)
- STALE_JOB_DAYS (default: 5)

---

## Out of Scope (Future)

- Automated application submission via Greenhouse POST API
- Browser automation for ATS form filling (Workday, iCIMS, etc.)
- LinkedIn networking automation
- Interview preparation materials
- Salary negotiation assistant
