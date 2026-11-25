# Agent Workflow Generator

A local CLI for Python 3.9 or later. It uses the Python standard library and generates Markdown files. The questionnaire and initial project scan run locally. When you open the project with an LLM, it can use the `update-context` skill to refine the context.

## Try the three examples

From the generator's root directory, copy the examples to a temporary directory so you can rerun them.

```sh
demo_dir=$(mktemp -d)
cp -R examples/. "$demo_dir/"

python3 workflow.py init "$demo_dir/empty"
python3 workflow.py init "$demo_dir/starter"
python3 workflow.py init "$demo_dir/existing"
```

- **empty** contains only a placeholder file. Leave the programming language blank if you want to decide later.
- **starter** contains a JavaScript project. The preview includes JavaScript conventions and the detected `npm run test` command.
- **existing** contains agent instructions and product context. Choose `edit` to change a file, or `complete` to preview adding a section to `AGENTS.md` and creating `docs/agent-workflow.md`.

The CLI shows a diff before writing. At the interactive prompt, enter `y` in English or `o` in French to apply the changes. Use `--dry-run` to preview the changes or `--apply` to write them immediately after displaying the diff. In non-interactive mode, pass your answers as options.

```sh
python3 workflow.py init "$demo_dir/starter" --non-interactive --dry-run \
  --detail 9 --tests 8 --test-strategy tdd --coverage 85 --coverage-scope changed \
  --git 8
```


## How the project scan changes initialization

After the language prompts, the CLI scans the target folder before asking project questions.

- In an empty folder, it asks about the project's goal, users, first milestone, and constraints.
- In an existing project, it lists the languages, package scripts, and representative files it found. It summarizes available project descriptions, uses detected facts to prefill the context, and asks whether you want to correct or add anything.
- If it finds context or harness files, it shows excerpts from the existing context, README, or instructions when available. To make corrections or additions, choose `edit` to select a recognized file, inspect its headings or numbered lines, and append text or replace a line range. Enter `:end` on its own line to finish the replacement text. Select file `0` to preview the edits together. Choose `complete` to propose missing workflow files and links, or `skip` to exit. Non-interactive runs use the completion path and preserve existing context and skills.

The scan and edits run locally. The CLI uses filenames, manifests, and document headings to identify what is present. You supply the wording for changes to existing files.

## Options

- `--detail 1..10` controls how much detail to include in the context. Levels 4, 7, and 9 each add a section.
- `--language` accepts any programming language and can be repeated. Built-in profiles add language-specific guidance. For other languages, the context indicates where to document conventions.
- `--tests 0..10` controls testing requirements. At level 0, the testing strategy remains open and the agent follows existing project instructions. At higher levels, use `--test-strategy tdd|after|custom` and `--test-rules` to describe how to write and run tests. Use `--coverage 0..100` and `--coverage-scope global|changed` to set a target to check with the project's tooling.
- `--git 0..10` controls which Git tasks the harness delegates to the agent. At level 0, Git operations are manual. Use `--git-policy undecided` to record that the policy is still open. At levels 1–3 the agent prepares a commit message, at levels 4–7 it can commit locally, and at levels 8–10 it can also push and open a GitHub pull request or GitLab merge request. Use `--commit-template` and `--review-template` to specify template paths. Merging and application deployment are manual.

The generator writes instructions for the agent to follow within its environment's permissions. It detects verification scripts declared in `package.json`. For other stacks, the context indicates that verification commands still need to be identified. The generator treats Git repositories directly under the target directory as components.

Rerunning `init` preserves existing context files and skills. To update their instructions, ask your agent to use the `update-context` skill.

## Languages

The first interactive prompt asks which language to use for the questionnaire. The next two prompts independently set the language of the generated context and harness, and the language the LLM should use in its replies. Each setting accepts `fr` or `en`. The CLI defaults to French, and the other two settings default to the CLI language.

In non-interactive mode, use the language options directly. This example uses French for the CLI, English for the generated files, and French for the LLM's replies.

```sh
python3 workflow.py init "$demo_dir/empty" --non-interactive --dry-run \
  --ui-language fr --docs-language en --response-language fr
```

The document language applies to generated text. The CLI preserves your free-form answers and existing instructions as written. It records the LLM's reply language in `AGENTS.md`.

## Portable agent roles

Initialization creates a Markdown role for `requirements-reviewer` and links to it in `AGENTS.md`. To add it to an existing harness, rerun `init` and choose `complete`.

Ask your model to follow the reviewer role and provide the original request and the diff. If it cannot read project files, paste the role and relevant context into the conversation. The reviewer examines code quality and traces each requirement to the delivered behavior. It returns a reasoned verdict, identifies unverified points, and lists manual acceptance tests with steps and expected results.

## TDD workflow

Select `tdd` with a test level above 0 to generate a workflow and three roles under `.agents/roles/`.

1. **Red** writes a focused test and records the expected failure.
2. **Green** makes the smallest correct production change that passes the test.
3. **Refactor** improves production code or tests while preserving behavior and coverage.

Follow the linked workflow in `AGENTS.md`. Tools with subagent support can delegate the roles sequentially. A single model can also follow the same sequence. The generator creates the instructions locally.

## Agent tools

After the language settings, choose one or more tools using a comma-separated list. The default, `portable`, keeps the Markdown harness. Choosing a native tool adds profiles that refer to the same Markdown role files.

| Tool | Generated integration |
| --- | --- |
| `codex` | `.codex/agents/*.toml` |
| `copilot` | `.github/agents/*.agent.md` |
| `claude-code` | `.claude/agents/*.md` and an `@AGENTS.md` import in `CLAUDE.md` |

Use a repeatable `--tool` option in non-interactive mode, for example:

```sh
python3 workflow.py init "$demo_dir/starter" --non-interactive --dry-run \
  --tool codex --tool copilot --tool claude-code --tests 5 --test-strategy tdd
```

To add another tool to an initialized project, rerun `init` and choose `complete`. Existing native profiles are preserved. Installed TDD roles are included when adding a tool, so you can reuse them without reselecting the test strategy.
