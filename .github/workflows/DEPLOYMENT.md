# 🚀 Deployment & Tagging Documentation

## Overview

Our CI/CD pipeline (`github-actions.yml`) includes an automated Git tagging mechanism. Whenever code is successfully deployed to **Staging** or **Production**, GitHub Actions automatically tags the repository commit with the release version pulled from `package.json`.

> 📌 **Note:** Deployment tagging is disabled for **Development (`dev`)** builds to keep the Git tag history clean and prevent unnecessary noise.

---

## 📐 Tag Naming Schemes

The tag naming structure varies depending on the target environment:

| Target Environment | Tag Format | Example | Behavior |
| :--- | :--- | :--- | :--- |
| **Development** | *None* | *No tag created* | Tagging skipped automatically. |
| **Staging** | `staging-v<version>-<run_number>` | `staging-v1.2.0-142` | Unique tag generated per deployment using the GitHub Actions run ID. |
| **Production** | `v<version>` | `v1.2.0` | Clean semantic versioning tag. Overwrites tag using force push if re-deployed. |