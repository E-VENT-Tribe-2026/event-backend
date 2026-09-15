# Capstone-3 Baseline Documentation & Post-Action Report

## Executive Summary
This document records the establishment, tagging, and verification of the **Capstone-3 baseline** for both the frontend and backend repositories. Creating this baseline ensures that the initial state of the application—prior to any Capstone-3 development—is permanently marked, allowing for future analysis, measurement, and security/performance auditing.

---

## 1. Objectives & Requirements
* **Tagging:** Identify and tag the exact repository states immediately preceding Capstone-3 development.
* **Accessibility:** Push baseline tags to shared remote repositories so all team members can check them out.
* **Dependency Locking:** Verify and record exact dependency versions to ensure reproducible installations.
* **Functional Verification:** Confirm that the tagged states successfully build, start, and run.

---

## 2. Methodology & Actions Performed

### Step 1: Identifying the Pre-Capstone-3 State
For each repository (`frontend` and `backend`), the repository terminal was used to review commit histories on the primary integration branch (`main` / `dev`). 
* **Action:** Executed `git log --oneline` to locate the final stable commit before any Capstone-3 pull requests or feature branches were merged.
* **Result:** Identified the target commit hash representing the clean Capstone-2 closing state.

### Step 2: Creating and Pushing Baseline Tags
Annotated tags were created to permanently mark these historical states and pushed to the remote repository.
```bash
# Executed in both frontend and backend repositories
git tag -a capstone-3-baseline <COMMIT_HASH> -m "Baseline state before Capstone-3 development"
git push origin capstone-3-baseline
```
* **Result:** Both repositories now contain the `capstone-3-baseline` tag, available globally for the entire team.

### Step 3: Dependency Version Verification
To satisfy the requirement that external package versions remain reproducible:
* Checked for lockfiles (`package-lock.json`, `yarn.lock`, `poetry.lock`, or pinned requirements).
* Confirmed that exact versions at the tagged commit are locked and tracked by version control.

### Step 4: Smoke Testing and Execution
* **Action:** Checked out the tag locally via `git checkout capstone-3-baseline`.
* **Result:** Cleanly built and started both the frontend and backend applications to verify that the baseline state is fully functional.

---

## 3. Acceptance Criteria Checklist

| Acceptance Criterion | Status | Notes / Verification Method |
| :--- | :---: | :--- |
| Frontend repository contains a baseline tag | **Passed** | `capstone-3-baseline` tag created and pushed |
| Backend repository contains a baseline tag | **Passed** | `capstone-3-baseline` tag created and pushed |
| Tags mark state before Capstone-3 work was merged | **Passed** | Verified via `git log` prior to tag creation |
| Accessible to all team members | **Passed** | Pushed to remote (`origin`) repository |
| Exact dependency versions known/fixed | **Passed** | Verified via project lockfiles |
| Tagged state starts and runs successfully | **Passed** | Verified via local checkout and test startup |
| Permanent markers for the semester | **Passed** | Stored securely in Git history |