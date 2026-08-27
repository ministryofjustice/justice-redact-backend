# Contributing to Justice Redact

Welcome! To protect our shared environments while keeping development fast, we use a **Draft PR Deployment Pattern** across our frontend and backend repositories.

---

## 🚀 Branching & Pull Request Workflow

### **1. Target Branch **
All feature branches and bug fixes must target the **`dev`** branch.

```bash
git checkout dev
git pull origin dev
git checkout -b feature/my-new-feature
```

### **2. Open a Draft PR First 📝 **
When you are ready to push your work to GitHub, open your Pull Request against dev as a Draft Pull Request:

Via GitHub Web: Click the green dropdown arrow next to Create Pull Request and select Create Draft Pull Request.

Via GitHub CLI:
```bash
gh pr create --draft --base dev
```

Why Draft? Commits pushed to a Draft PR run automated linting and code checks, but will NOT build or deploy to the shared justice-redact-dev Kubernetes environment. This prevents unfinished or broken code from affecting other developers.

### **3. Deploy to Dev Environment ("Ready for Review") 🧪 **
When your work is ready to be tested on the live MoJ Cloud Platform dev environment:

Open your Draft PR on GitHub.

Scroll to the bottom of the PR page and click "Ready for review" (or run gh pr ready).

What happens: The GitHub Actions pipeline builds a container image tagged node-qa-<commit_sha> and deploys it directly to the justice-redact-dev namespace.

### **4. Need to Keep Iterating? Convert Back to Draft 🔄 **
If you find an issue during testing and need to make further WIP commits without triggering new deployments:

Click "Convert to draft" in the right-hand sidebar under the Reviewers section (or run gh pr ready --undo).

Subsequent pushes will go back to being silent draft commits.

### **5. Merging & Release Pipeline 🏁 **
Once your PR is reviewed and approved, merge it into dev.

Merging into dev automatically triggers the main deployment pipeline to update the canonical development environment.

Releases to staging and prod are managed by promoting code via their respective branches.