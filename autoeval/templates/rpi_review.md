<!-- template_id: rpi_review -->
<!-- template_version: 2.2.0 -->

# Research Artifact Instruction

Purpose:
- Build repository familiarity context for a target repository when `autoeval` is initialized there for the first time.
- This artifact is repository-level and not task-specific.
- It should remain reusable across future tasks in the same target repository.

## Structure and Guidelines
1. Cover the whole repository architecture and capture the hierarchical flow between the modules and core components.
2. Generate a directory/modules level overview of the repository with single line comments against each of the modules explaining their primary purpose.
3. Divide the research/technical oveview report into multiple sections with each section highlighting major components or execution logic for the repository.
4. Include details from first principles about primary execution workflows for each section, include snippets from actual repository and skeletal structures to support the documentation.
5. Include end-to-end flow traces for key user/system paths.
6. Include separate sections for integration methodology and extensibility of the repository with new functionalities, deployment/runtime/testing setup, and known gaps, risks, etc.
8. While preparing structure highlights, follow the repository `.gitignore` rules; include ignored paths only when they are directly relevant to the request.

## Update Rules
- Keep links/file references actionable and current.
- If behavior changes, update only affected sections with concrete diffs in understanding.