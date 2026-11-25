#!/usr/bin/env python3
"""Initialize a local agent workflow."""
import argparse
import difflib
import json
import os
import re
import sys
import tempfile
from pathlib import Path


PROFILES = {
    "python": ('Suivre le formatage du projet et les conventions de nommage Python. Isoler les dépendances dans un environnement dédié.', "Follow the project's formatting and Python naming conventions. Keep dependencies in a dedicated environment."),
    "javascript": ('Respecter le système de modules existant. Traiter explicitement les erreurs asynchrones.', 'Follow the existing module system. Handle asynchronous errors explicitly.'),
    "typescript": ('Préciser les types aux frontières du système et limiter les assertions de type.', 'Specify types at system boundaries and limit type assertions.'),
    "php": ('Suivre les namespaces et le chargement automatique du projet. Typer les interfaces publiques selon la version ciblée.', "Follow the project's namespaces and autoloading conventions. Type public interfaces according to the target version."),
    "c#": ('Suivre les conventions de nommage et de nullabilité du projet. Garder les dépendances explicites.', "Follow the project's naming and nullability conventions. Keep dependencies explicit."),
    "go": ('Formater avec gofmt et traiter explicitement les erreurs.', 'Format with gofmt and handle errors explicitly.'),
    "rust": ('Suivre rustfmt, modéliser les erreurs avec Result et éviter les unwrap dans les chemins faillibles.', 'Use rustfmt, model errors with Result, and avoid unwrap in fallible paths.'),
    "java": ("Respecter les conventions de packages et les versions d'API ciblées. Préserver les contrats d'exception.", 'Follow package conventions and target API versions. Preserve exception contracts.'),
}
MANIFESTS = {
    "pyproject.toml": "Python", "requirements.txt": "Python",
    "tsconfig.json": "TypeScript", "composer.json": "PHP",
    "go.mod": "Go", "Cargo.toml": "Rust", "pom.xml": "Java",
    "Package.swift": "Swift", "Gemfile": "Ruby", "pubspec.yaml": "Dart",
}
EXTENSIONS = {
    ".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".php": "PHP",
    ".cs": "C#", ".go": "Go", ".rs": "Rust", ".java": "Java",
    ".kt": "Kotlin", ".swift": "Swift", ".rb": "Ruby", ".cpp": "C++",
    ".c": "C", ".dart": "Dart", ".lua": "Lua", ".ex": "Elixir",
}
EXCLUDED = {"node_modules", "vendor", "Library", "dist", "build", "target", "__pycache__"}
MARKER = "<!-- agent-workflow:init -->"
CONTEXT = "docs/project-context.md"
DEVELOP = ".agents/skills/develop/SKILL.md"
UPDATE = ".agents/skills/update-context/SKILL.md"
ROLES = ".agents/roles"
REVIEWER = f"{ROLES}/requirements-reviewer.md"
LEGACY_REVIEWER = ".codex/agents/requirements-reviewer.toml"
TDD = ".agents/skills/tdd/SKILL.md"
TOOLS = ("portable", "codex", "copilot", "claude-code")
ROLE_NAMES = ("requirements-reviewer", "tdd-red", "tdd-green", "tdd-refactor")


def translator(language):
    return lambda french, english: english if language == "en" else french


ui = translator("fr")


def language_profile(language, tr, fallback):
    profile = PROFILES.get(language.casefold())
    return tr(*profile) if profile else fallback


def inventory(root):
    """Find local evidence, bounded to four levels below each component."""
    languages = set()
    commands = []
    evidence = []
    populated = False
    description = ""
    package_manager = "npm"
    for lock, manager in (("bun.lock", "bun"), ("bun.lockb", "bun"),
                          ("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn")):
        if (root / lock).is_file():
            package_manager = manager
            break
    for directory, children, filenames in os.walk(root):
        folder = Path(directory)
        depth = len(folder.relative_to(root).parts)
        children[:] = sorted(
            name for name in children
            if depth < 4 and not name.startswith(".") and name not in EXCLUDED
            and not (folder / name / ".git").exists()
        )
        for name in sorted(filenames):
            if name.startswith(".") or (folder / name).is_symlink():
                continue
            populated = True
            language = MANIFESTS.get(name) or EXTENSIONS.get(Path(name).suffix)
            if language:
                languages.add(language)
            if len(evidence) < 8 and (language or name in {"README.md", "package.json", "Makefile"}):
                evidence.append((folder / name).relative_to(root).as_posix())
        if depth == 0 and "package.json" in filenames and not (root / "package.json").is_symlink():
            package = json.loads((root / "package.json").read_text(encoding="utf-8"))
            if isinstance(package.get("description"), str):
                description = package["description"].strip()
            for script in sorted(package.get("scripts", {})):
                if re.fullmatch(r"[A-Za-z0-9_:-]+", script) and (
                    script.split(":")[0] in {"test", "lint", "build", "typecheck", "coverage", "check"}
                ):
                    commands.append(f"{package_manager} run {script}")
    return sorted(languages), commands, evidence, populated, description


def bounded(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(ui('valeur attendue entre {0} et {1}', 'expected a value between {0} and {1}').format(low, high))
        return number
    return parse


def ask(label, default=""):
    answer = input(f"{label}" + (f" [{default}]" if default else "") + " : ").strip()
    return answer or default


def ask_choice(label, default, convert):
    while True:
        try:
            return convert(ask(label, str(default)))
        except (ValueError, argparse.ArgumentTypeError):
            print(ui('Valeur non valide. Réessaie.', 'Invalid value. Try again.'))


def select(options):
    def parse(value):
        if value not in options:
            raise ValueError(value)
        return value
    return parse


def configure(args, detected, interactive, populated=False, goal=""):
    if args.goal is None and goal:
        args.goal = goal
    args.languages = args.language if args.language is not None else detected
    if interactive and not populated:
        for field, question in (
            ("goal", ui("Quel est l'objectif du projet ?", "What is the goal of the project?")),
            ("audience", ui("À qui s'adresse le projet ?", "Who is the project for?")),
            ("first_result", ui("Quel premier résultat veux-tu obtenir ?", "What should the first milestone deliver?")),
            ("constraints", ui("Quelles contraintes sont déjà connues ?", "What constraints are already known?")),
        ):
            if getattr(args, field) is None:
                setattr(args, field, ask(question))
    if interactive and args.language is None:
        answer = ask(
            ui("Langages séparés par des virgules (Entrée pour conserver la détection)",
               "Comma-separated programming languages (Enter to keep detected values)"),
            ", ".join(detected),
        )
        args.languages = [item.strip() for item in answer.split(",") if item.strip()]
    for field, question, default, low in (
        ("detail", ui('Détail du contexte (1–10)', 'Context detail (1–10)'), 5, 1),
        ("tests", ui('Rigueur des tests (0–10)', 'Test rigor (0–10)'), 0, 0),
        ("git", ui('Autonomie Git (0–10)', 'Git autonomy (0–10)'), 0, 0),
    ):
        if getattr(args, field) is None:
            value = ask_choice(question, default, bounded(low, 10)) if interactive else default
            setattr(args, field, value)
    if args.tests and interactive and args.test_strategy is None:
        args.test_strategy = ask_choice(
            ui('Stratégie (tdd, after, custom)', 'Test strategy (tdd, after, custom)'), "after", select(("tdd", "after", "custom"))
        )
    if args.test_strategy == "custom" and interactive and not args.test_rules:
        args.test_rules = ask(ui("Outils, emplacement et moments d'exécution des tests", 'Test tools, location, and when to run tests'))
    if args.tests and interactive and args.coverage is None:
        unset = ui("aucun", "none")
        args.coverage = ask_choice(
            ui('Objectif de couverture en % (aucun = à définir)', 'Coverage target in % (none = to be defined)'), unset,
            lambda value: None if value == unset else bounded(0, 100)(value),
        )
    if args.coverage is not None and interactive and args.coverage_scope is None:
        args.coverage_scope = ask_choice(
            ui('Périmètre de couverture (global, changed)', 'Coverage scope (global, changed)'), "global", select(("global", "changed"))
        )


def test_policy(args):
    tr = translator(args.docs_language)
    if not args.tests:
        return tr('Stratégie à préciser. Suivre les consignes existantes et clarifier les besoins de la tâche si nécessaire.', 'Testing strategy to be defined. Follow existing instructions and clarify task requirements when needed.')
    strategy = {
        "tdd": tr("Écrire un test qui échoue avant de modifier le comportement, puis vérifier qu'il passe.", 'Write a failing test before changing behavior, then verify that it passes.'),
        "after": tr('Écrire ou adapter les tests après implémentation et les exécuter avant livraison.', 'Write or update tests after implementation and run them before delivery.'),
        "custom": tr('Appliquer la stratégie personnalisée. Clarifier ses éléments manquants au besoin.', 'Follow the custom strategy and clarify missing details when needed.'),
        None: tr("Préciser le moment d'écriture des tests dans le contexte.", 'Record when to write tests in the project context.'),
    }
    lines = [
        strategy[args.test_strategy],
        tr('Ajouter ou adapter les tests lorsque le comportement change. Exécuter les tests ciblés.', 'Add or update tests when behavior changes. Run the targeted tests.'),
    ]
    if args.test_rules:
        lines.append(args.test_rules)
    if args.tests >= 4:
        lines.append(tr("Avant livraison, exécuter la suite pertinente et relever la couverture si l'outillage le permet.", 'Before delivery, run the relevant suite and report coverage when tooling supports it.'))
    if args.tests >= 8:
        lines.append(tr('Vérifier la couverture des composants touchés et appliquer les seuils configurés dans la CI existante si elle le permet.', 'Check coverage in affected components and enforce configured thresholds in existing CI when supported.'))
    if args.coverage is not None:
        scope = tr('du code modifié', 'for changed code') if args.coverage_scope == "changed" else tr('globale', 'across the project')
        lines.append(tr('Objectif de couverture {0} : {1} %. Préciser la métrique et la commande si elles restent à définir.', 'Coverage target {0}: {1}%. Define the metric and command if they are still open.').format(scope, args.coverage))
    return "\n".join(f"- {line}" for line in lines)


def git_policy(args):
    tr = translator(args.docs_language)
    if args.git == 0:
        if args.git_policy == "undecided":
            return (tr("Politique à préciser. En attendant, consulter l'état et les diffs en lecture seule et laisser les opérations Git à l'utilisateur.", 'Git policy to be defined. Until then, inspect Git status and diffs in read-only mode and leave Git operations to the user.'))
        return (tr("Consulter l'état et les diffs en lecture seule. Laisser les opérations Git à l'utilisateur. Le changement de cette règle requiert une demande explicite.", "Inspect Git status and diffs in read-only mode. Leave Git operations to the user. Change this policy only at the user's explicit request."))
    lines = [tr('Vérifier le diff et respecter les modifications présentes.', 'Review the diff and preserve existing changes.')]
    if args.git < 4:
        lines.append(tr("Préparer le message de commit et laisser les opérations Git à l'utilisateur.", 'Prepare the commit message and leave Git operations to the user.'))
    else:
        lines.append(tr('Utiliser une branche de travail et créer des commits locaux après les vérifications prévues.', 'Use a working branch and create local commits after completing the required checks.'))
    if args.git >= 8:
        lines.append(tr('Pousser la branche de travail et ouvrir une PR GitHub ou une MR GitLab selon le dépôt distant et les permissions disponibles.', 'Push the working branch and open a GitHub PR or GitLab MR according to the remote and available permissions.'))
        lines.append(tr('Inclure un titre, un résumé du changement et les vérifications effectuées.', 'Include a title, a summary of the change, and the checks performed.'))
    lines.append(tr("Utiliser les modèles du projet lorsqu'ils existent.", "Use the project's templates when available."))
    if args.commit_template:
        lines.append(tr('Modèle de commit : {0}.', 'Commit template: {0}.').format(args.commit_template))
    if args.git >= 8 and args.review_template:
        lines.append(tr('Modèle de PR/MR : {0}.', 'PR/MR template: {0}.').format(args.review_template))
    lines.append(tr("Laisser la fusion et le déploiement applicatif à l'utilisateur.", 'Leave merging and application deployment to the user.'))
    return "\n".join(f"- {line}" for line in lines)


def context(args, languages, commands, components, evidence, existing_context=None):
    tr = translator(args.docs_language)
    lines = [tr('# Contexte du projet', '# Project context'), "", MARKER, ""]
    goal = args.goal
    if not goal and existing_context:
        goal = tr("[Voir le contexte existant]({0})", "[See the existing context]({0})").format(
            Path(existing_context).name
        )
    for title, value in (
        (tr('Objectif', 'Goal'), goal), (tr('Utilisateurs', 'Users'), args.audience),
        (tr('Premier résultat', 'First milestone'), args.first_result), (tr('Contraintes', 'Constraints'), args.constraints),
    ):
        label = tr("{0} : {1}", "{0}: {1}")
        lines.append("- " + label.format(title, value or tr("à préciser", "to be defined")))
    if args.context_notes:
        lines.extend(["", tr("## Compléments de contexte", "## Additional context"), "", args.context_notes])
    lines.extend(["", tr('## Langages et conventions', '## Languages and conventions'), ""])
    for language in languages:
        profile = language_profile(language, tr, tr("Reprendre les conventions du projet et compléter ce profil lorsque l'outillage est défini.", "Follow the project's conventions and complete this profile once the tooling is known."))
        lines.append(f"- **{language}**. {profile}")
    if not languages:
        lines.append(tr("Langage à décider. Lorsque la tâche l'exige, proposer une stack selon les besoins et consigner le choix validé.", 'Language to be decided. When the task requires it, propose a stack based on the requirements and record the approved choice.'))
    lines.extend(["", tr('## Vérifications', '## Checks'), ""])
    lines.extend(f"- `{command}`" for command in commands)
    if not commands:
        lines.append(tr("Commandes à préciser à partir de l'outillage réellement disponible.", "Identify the checks supported by the project's tooling."))
    if evidence:
        lines.extend(["", tr("## Fichiers repérés", "## Files detected"), ""])
        lines.extend(f"- `{path}`" for path in evidence)
    if components:
        lines.extend(["", tr('## Composants', '## Components'), ""])
        for component in components:
            lines.append(f"- [`{component.name}`](../{component.name}/AGENTS.md)")
    if args.detail >= 4:
        lines.extend(["", tr('## Architecture et sources de vérité', '## Architecture and sources of truth'), "",
                      tr("Renseigner les points d'entrée, les responsabilités et les documents de référence confirmés.", 'Record confirmed entry points, responsibilities, and reference documents.')])
    if args.detail >= 7:
        lines.extend(["", tr('## Décisions et questions ouvertes', '## Decisions and open questions'), "",
                      tr('Consigner les décisions validées, leur motivation et les sujets restant à arbitrer.', 'Record approved decisions, their rationale, and open questions.')])
    if args.detail >= 9:
        lines.extend(["", tr('## Contrats et workflows récurrents', '## Contracts and recurring workflows'), "",
                      tr('Documenter les contrats entre composants, les scénarios de validation et les procédures récurrentes lorsque ces éléments sont établis.', 'Document component contracts, validation scenarios, and recurring procedures when they are established.')])
    lines.extend(["", tr('## Tests — niveau {0}', '## Tests — level {0}').format(args.tests), "", test_policy(args),
                  "", tr('## Git — niveau {0}', '## Git — level {0}').format(args.git), "", git_policy(args), ""])
    return "\n".join(lines)


def skill(name, description, body):
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body.strip()}\n"


def develop_skill(tr):
    return skill("develop", tr(
        "Cadrer, implémenter et vérifier une tâche dans ce projet.",
        "Scope, implement, and verify a development task in this project.",
    ), tr("""
1. Lire l'AGENTS.md racine, puis les instructions du composant touché.
2. Lire les sections pertinentes du contexte. Si une décision ouverte bloque la tâche, la clarifier avec l'utilisateur.
3. Vérifier les conventions et commandes dans les fichiers du projet. Appliquer la stratégie de test au moment prévu.
4. Après le changement, exécuter les vérifications demandées et signaler leurs résultats ou les contrôles indisponibles.
5. Suivre la politique Git du projet. Si une décision change, appliquer le skill update-context.
""", """
1. Read the root AGENTS.md, then the instructions for the affected component.
2. Read the relevant context sections. If an open decision blocks the task, clarify it with the user.
3. Verify conventions and commands in the project files. Apply the testing strategy at the prescribed stage.
4. Run the required checks after the change and report the results or any checks that were unavailable.
5. Follow the project's Git policy. If a decision changes, apply the update-context skill.
"""))


def update_skill(tr):
    return skill("update-context", tr(
        "Actualiser le contexte, les consignes et les skills après une décision ou un changement vérifié.",
        "Update project context, instructions, and skills after a decision or a verified change.",
    ), tr("""
1. Identifier le changement et les composants concernés. Retrouver la décision validée ou la source qui confirme le nouvel état.
2. Mettre à jour les règles générales dans AGENTS.md, les éléments métier ou d'architecture dans le contexte, et les procédures récurrentes dans les skills.
3. Pour un changement local, privilégier les instructions du composant. Pour un contrat partagé, examiner les instructions de chaque partie.
4. Vérifier les liens, commandes et règles touchés. Conserver la langue des documents, les décisions encore valides et la politique Git sauf demande explicite.
5. Résumer les fichiers actualisés et noter les décisions qui restent ouvertes.
""", """
1. Identify the change and affected components. Find the approved decision or evidence of the new state.
2. Update general rules in AGENTS.md, product and architecture details in the context, and recurring procedures in the skills.
3. Prefer component instructions for local changes. For shared contracts, review the instructions on each side.
4. Verify affected links, commands, and rules. Keep the document language, approved decisions, and the Git policy unless the user asks for a change.
5. Summarize the updated files and record decisions that remain open.
"""))


def review_agent(tr, response_language):
    description = tr(
        "Vérifie le code et sa conformité à la demande. Rend un verdict motivé et propose des tests manuels.",
        "Reviews code and checks it against the request. Returns a reasoned verdict and manual tests.",
    )
    instructions = tr(
        """Mène une revue en lecture seule. Laisse les fichiers et les opérations Git à leur auteur.
Retrouve la demande d’origine, les clarifications validées et les critères d’acceptation. Si la demande ne t’a pas été transmise, signale ce qui manque et demande la source avant de conclure à la conformité.
Compare chaque exigence au comportement livré dans le diff et dans les parcours d’exécution pertinents. Relève aussi les défauts du code, les régressions et les lacunes de test. Cite les fichiers et les lignes quand tu disposes de preuves.
Rends un verdict global unique et explique précisément ce qui le justifie.
- Conforme : toutes les exigences identifiées sont satisfaites et les preuves permettent de conclure.
- Conforme avec réserve : aucun écart bloquant n’est établi, mais un point reste incertain, non vérifié ou affecté par un écart mineur. Indique ce qui lèverait la réserve.
- Non conforme : une exigence explicite est omise ou violée, ou un défaut bloque le comportement attendu. Décris l’impact et la correction attendue.
Liste chaque exigence avec son résultat et sa preuve ou sa limite. Distingue les contrôles exécutés des contrôles proposés.
Termine par des tests manuels liés à la demande. Pour chacun, indique les préconditions, les étapes, le résultat attendu et l’exigence couverte. Inclue le parcours nominal et les cas limites pertinents.""",
        """Review in read-only mode. Leave file changes and Git operations to the author.
Recover the original request, approved clarifications, and acceptance criteria. If the request was not provided, state what is missing and ask for the source before declaring compliance.
Compare each requirement with the delivered behavior in the diff and relevant execution paths. Also flag code defects, regressions, and test gaps. Cite files and lines when evidence is available.
Return one overall verdict and explain precisely what supports it.
- Compliant: all identified requirements are met and the evidence supports that conclusion.
- Compliant with reservations: no blocking gap is established, but a point is uncertain, unverified, or affected by a minor issue. Explain what would clear each reservation.
- Non-compliant: an explicit requirement is omitted or violated, or a defect blocks the expected behavior. Explain the impact and the required correction.
List every requirement with its result and evidence or limitation. Distinguish checks performed from checks proposed.
End with manual acceptance tests tied to the request. For each, include prerequisites, steps, the expected result, and the requirement covered. Cover the main flow and relevant edge cases.""",
    )
    language = {"fr": tr("français", "French"), "en": tr("anglais", "English")}[response_language]
    instructions += "\n" + tr("Rédige le rapport en {0}.", "Write the report in {0}.").format(language)
    return f"# requirements-reviewer\n\n{description}\n\n{instructions}\n"


def tdd_workflow(tr):
    roles = {
        "tdd-red": tr(
            """Choisis un comportement à partir de la demande et écris un test ciblé qui exprime le résultat attendu. Exécute-le avant de modifier le code applicatif. Vérifie que l’échec révèle le comportement manquant, plutôt qu’un problème de configuration ou de données de test. Si le test passe déjà, choisis un autre comportement à couvrir ou indique que celui-ci existe déjà. Transmets le test, sa commande, l’échec observé et l’exigence couverte.""",
            """Choose one behavior from the request and write a focused test that expresses the expected outcome. Run it before changing application code. Verify that it fails because the behavior is missing. Resolve setup or fixture errors before claiming a Red result. If the test already passes, pick another behavior or report that this one already exists. Hand off the test, its command, the observed failure, and the requirement it covers.""",
        ),
        "tdd-green": tr(
            """Reprends le test et l’échec transmis par Red. Implémente le plus petit changement correct qui satisfait le comportement attendu. Conserve les assertions et les attentes établies par Red. Lance le test ciblé et les tests voisins pertinents. Transmets les changements et les résultats à Refactor.""",
            """Use the failing test and evidence handed off by Red. Implement the smallest correct change that satisfies the expected behavior. Preserve the assertions and expectations established by Red. Run the focused test and relevant nearby tests. Hand off the changes and results to Refactor.""",
        ),
        "tdd-refactor": tr(
            """Pars d’un état vert. Améliore la lisibilité, la structure ou la maintenabilité du code et, si utile, des tests. Préserve le comportement observable, les attentes et la couverture. Exécute les tests pertinents après chaque modification significative. Si une exigence ou un comportement doit changer, ouvre un nouveau cycle Red. Signale les vérifications effectuées et les éventuels blocages.""",
            """Start from passing tests. Improve the readability, structure, or maintainability of the code and, where useful, the tests. Preserve observable behavior, expectations, and coverage. Run the relevant tests after each meaningful change. If a requirement or behavior needs to change, start a new Red cycle. Report the checks performed and any blockers.""",
        ),
    }
    body = tr(
        """1. Sélectionner un comportement à partir de la demande et des critères d’acceptation.
2. Suivre [Red](../../roles/tdd-red.md). Passer à Green quand l’échec attendu est observé.
3. Suivre [Green](../../roles/tdd-green.md). Passer à Refactor quand le test ciblé et les tests voisins passent.
4. Suivre [Refactor](../../roles/tdd-refactor.md), puis répéter le cycle pour le comportement suivant.
5. Transmettre entre les étapes la demande, le cas ciblé, les fichiers modifiés, la commande et le résultat des tests. Si un contrôle ne peut pas être exécuté, signaler le blocage avant de passer à la suite.

Exécuter les rôles en séquence sur les mêmes fichiers. Tu peux déléguer chaque rôle à un sous-agent si l’outil le permet, ou appliquer les trois rôles dans la même session. Suivre les préférences linguistiques et la politique de test du projet.""",
        """1. Choose a behavior from the request and acceptance criteria.
2. Follow [Red](../../roles/tdd-red.md). Move to Green when the expected failure is observed.
3. Follow [Green](../../roles/tdd-green.md). Move to Refactor when the focused and nearby tests pass.
4. Follow [Refactor](../../roles/tdd-refactor.md), then repeat for the next behavior.
5. Pass the request, focused case, changed files, test command, and results between stages. If a check cannot run, report the blocker before proceeding.

Run the roles sequentially on the same files. Delegate each role to a subagent when the tool supports it, or apply all three roles in one session. Follow the project's language preferences and testing policy.""",
    )
    description = tr("Développer en suivant les étapes Red, Green et Refactor.",
                     "Develop in Red, Green, and Refactor stages.")
    files = {f"{ROLES}/{name}.md": f"# {name}\n\n{instructions}\n"
             for name, instructions in roles.items()}
    files[TDD] = skill("tdd", description, body)
    return files


def safe_path(root, relative):
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(ui('Lien symbolique dans un chemin de sortie : {0}', 'Symbolic link in an output path: {0}').format(path))
    return path


def read_existing(root, relative):
    path = safe_path(root, relative)
    return path.read_bytes().decode("utf-8") if path.exists() else None


def native_agents(tools, role_names, tr):
    descriptions = {
        "requirements-reviewer": tr(
            "Vérifie le code et la conformité à la demande, puis propose des tests manuels.",
            "Reviews code and requirements compliance, then proposes manual acceptance tests.",
        ),
        "tdd-red": tr("Écrit un test ciblé et vérifie son échec attendu.",
                      "Writes a focused test and verifies its expected failure."),
        "tdd-green": tr("Implémente le changement minimal pour faire passer le test.",
                        "Implements the smallest correct change that passes the test."),
        "tdd-refactor": tr("Améliore le code ou les tests en préservant le comportement.",
                           "Improves the code or tests while preserving behavior."),
    }
    files = {}
    for name in role_names:
        role_path = f"{ROLES}/{name}.md"
        instructions = tr(
            "Lis AGENTS.md et {0} à la racine du projet. Applique le rôle Markdown à la tâche transmise.",
            "Read AGENTS.md and {0} from the project root. Follow the Markdown role for the task handed to you.",
        ).format(role_path)
        if name.startswith("tdd-"):
            instructions += " " + tr(
                "Effectue uniquement ton étape du cycle décrit dans {0}, puis transmets les résultats.",
                "Perform only your stage of the cycle described in {0}, then hand off the results.",
            ).format(TDD)
        description = json.dumps(descriptions[name], ensure_ascii=False)
        if "codex" in tools:
            files[f".codex/agents/{name}.toml"] = (
                f'name = "{name}"\ndescription = {description}\n'
                f"developer_instructions = {json.dumps(instructions, ensure_ascii=False)}\n"
            )
        profile = f"---\nname: {name}\ndescription: {description}\n---\n\n{instructions}\n"
        if "copilot" in tools:
            files[f".github/agents/{name}.agent.md"] = profile
        if "claude-code" in tools:
            files[f".claude/agents/{name}.md"] = profile
    return files


def plan(root, args, root_inventory, components):
    tr = translator(args.docs_language)
    proposals = {}
    _, commands, evidence, _, _ = root_inventory
    context_path = CONTEXT
    existing_context = read_existing(root, CONTEXT)
    if existing_context is not None and MARKER not in existing_context:
        context_path = "docs/agent-workflow.md"
        suffix = 2
        while True:
            alternative = read_existing(root, context_path)
            if alternative is None or MARKER in alternative:
                break
            context_path = f"docs/agent-workflow-{suffix}.md"
            suffix += 1
    proposals[context_path] = context(
        args, args.languages, commands, components, evidence,
        CONTEXT if context_path != CONTEXT else None,
    )
    proposals[DEVELOP] = develop_skill(tr)
    proposals[UPDATE] = update_skill(tr)
    proposals[REVIEWER] = review_agent(tr, args.response_language)
    review_link = tr(
        "- Pour une revue de livraison, utiliser [requirements-reviewer]({0}) et lui transmettre la demande d’origine.",
        "- For a delivery review, use [requirements-reviewer]({0}) and provide the original request.",
    ).format(REVIEWER)
    response = {
        "fr": tr("en français", "in French"),
        "en": tr("en anglais", "in English"),
    }[args.response_language]
    links = [
        tr("- Répondre à l’utilisateur {0}.", "- Respond to the user {0}.").format(response),
        tr('- Consulter [le contexte de travail]({0}) pour les conventions, les tests et Git.', '- Read the [working context]({0}) for conventions, tests, and Git.').format(context_path),
        tr('- Utiliser [develop]({0}) pour une tâche de développement.', '- Use [develop]({0}) for development tasks.').format(DEVELOP),
        tr('- Utiliser [update-context]({0}) pour actualiser les consignes et les skills.', '- Use [update-context]({0}) to update instructions and skills.').format(UPDATE),
    ]
    role_links = {REVIEWER: review_link}
    if args.tests and args.test_strategy == "tdd":
        proposals.update(tdd_workflow(tr))
        role_links[TDD] = tr(
            "- Pour les changements de comportement en TDD, suivre le [cycle Red → Green → Refactor]({0}).",
            "- For behavior changes under TDD, follow the [Red → Green → Refactor cycle]({0}).",
        ).format(TDD)
    if any(tool != "portable" for tool in args.tool):
        roles = [name for name in ROLE_NAMES
                 if f"{ROLES}/{name}.md" in proposals
                 or read_existing(root, f"{ROLES}/{name}.md") is not None]
        proposals.update(native_agents(args.tool, roles, tr))
    if "claude-code" in args.tool and not (root / "CLAUDE.md").is_symlink():
        claude = read_existing(root, "CLAUDE.md")
        if claude is None:
            proposals["CLAUDE.md"] = "@AGENTS.md\n"
        elif not re.search(r"(?m)^\s*@(?:\./)?AGENTS\.md\s*$", claude):
            separator = "\n" if claude.endswith("\n") else "\n\n"
            proposals["CLAUDE.md"] = claude + separator + "@AGENTS.md\n"
    links.extend(role_links.values())
    if context_path != CONTEXT:
        links.insert(0, tr('- Lire aussi [le contexte existant]({0}).', '- Also read the [existing context]({0}).').format(CONTEXT))
    links.append(tr("- En cas de conflit avec une consigne existante, demander quelle politique appliquer avant d'agir.", '- If an existing instruction conflicts, ask which policy applies before acting.'))
    if components:
        links.append(tr('- Avant de modifier un composant, lire son AGENTS.md et ses vérifications locales.', '- Before changing a component, read its AGENTS.md and local checks.'))
    existing = read_existing(root, "AGENTS.md")
    if existing is None:
        proposals["AGENTS.md"] = tr('# Instructions du projet\n\n', '# Project instructions\n\n') + MARKER + "\n" + "\n".join(links) + "\n"
    elif MARKER not in existing:
        proposals["AGENTS.md"] = (
            existing + ("\n" if existing.endswith("\n") else "\n\n")
            + MARKER + tr('\n## Workflow agentique\n\n', '\n## Agent workflow\n\n') + "\n".join(links) + "\n"
        )
    else:
        updated = existing.replace(f"[requirements-reviewer]({LEGACY_REVIEWER})",
                                   f"[requirements-reviewer]({REVIEWER})")
        missing_links = [link for path, link in role_links.items() if f"]({path})" not in updated]
        if missing_links:
            updated += ("\n" if updated.endswith("\n") else "\n\n") + "\n".join(missing_links) + "\n"
        if updated != existing:
            proposals["AGENTS.md"] = updated
    for component in components:
        local_languages, local_commands, _, _, _ = inventory(component)
        parent = tr('- Consulter les [instructions du workspace](../AGENTS.md).', '- Read the [workspace instructions](../AGENTS.md).')
        rules = ["- {}. {}".format(language, language_profile(
            language, tr, tr("Respecter les conventions locales.", "Follow local conventions.")
        ))
                 for language in local_languages]
        checks = [tr('- Vérifier avec `{0}`.', '- Check with `{0}`.').format(command) for command in local_commands]
        proposals[f"{component.name}/AGENTS.md"] = (
            f"# {component.name}\n\n" + "\n".join([parent] + rules + checks) + "\n"
        )
    changes = {}
    for relative, content in proposals.items():
        previous = read_existing(root, relative)
        if previous is None or (relative in {"AGENTS.md", "CLAUDE.md"} and previous != content):
            changes[relative] = (previous, content)
    return changes


def harness_files(root, components):
    candidates = []
    base_files = (
        "AGENTS.md", "CLAUDE.md", "GEMINI.md", CONTEXT, "docs/agent-workflow.md",
        ".github/copilot-instructions.md", ".cursorrules", ".codex/config.toml",
    )
    patterns = (
        "docs/agent-workflow-*.md", ".agents/skills/*/SKILL.md", ".agents/roles/*.md",
        ".claude/skills/*/SKILL.md", ".claude/agents/*.md", ".github/agents/*.agent.md",
        ".github/skills/*/SKILL.md", ".cursor/rules/*.mdc", ".codex/agents/*.toml",
    )
    for folder in (root, *components):
        paths = [folder / name for name in base_files]
        for pattern in patterns:
            paths.extend(sorted(folder.glob(pattern)))
        for path in paths:
            relative = path.relative_to(root).as_posix()
            if path.is_file() and path.resolve() == path:
                candidates.append(relative)
    return list(dict.fromkeys(candidates))


def summarize_project(root, files, description):
    goal = ""
    sources = [name for name in files if name.startswith("docs/") and name.endswith(".md")]
    sources.extend(name for name in ("README.md", "AGENTS.md") if name not in sources)
    excerpts = []
    for relative in sources[:5]:
        path = root / relative
        if not path.is_file() or path.resolve() != path:
            continue
        with path.open(encoding="utf-8", errors="replace") as document:
            content = document.read(8192)
        excerpt = ""
        fenced = False
        for line in content.splitlines():
            line = line.strip()
            if line.startswith(("```", "~~~")):
                fenced = not fenced
            if fenced or not line or line.startswith(("#", "<", "!", "[", "---", "```", "~~~")):
                continue
            match = re.match(r"^(?:[-*] )?(?:objectif|goal|purpose)\s*:\s*(.+)$", line, re.IGNORECASE)
            if match and match[1].casefold() not in {"à préciser", "to be defined"}:
                if not goal:
                    goal = match[1]
                excerpt = line
                break
            if not excerpt and line[0].isalnum():
                excerpt = line
        if excerpt:
            excerpts.append((relative, excerpt))
    if description:
        excerpts.append(("package.json", description))
    print(ui("Synthèse des éléments repérés", "Summary of available project information"))
    for relative, excerpt in excerpts:
        excerpt = " ".join(excerpt.split())
        print(f"- {relative}: {excerpt[:220]}" + ("…" if len(excerpt) > 220 else ""))
    if not excerpts:
        print(ui("Aucune description trouvée dans les fichiers de référence.",
                 "No description found in the reference files."))
    return goal or description


def edit_harness(root, files):
    changes = {}
    while True:
        for number, relative in enumerate(files, 1):
            print(f"{number}. {relative}")
        number = ask_choice(
            ui("Fichier à modifier (0 = terminer)", "File to edit (0 = done)"),
            0, bounded(0, len(files)),
        )
        if number == 0:
            return changes
        relative = files[number - 1]
        original = read_existing(root, relative)
        if original is None:
            print(ui("Le fichier a disparu.", "The file is no longer available."))
            continue
        previous, current = changes.get(relative, (original, original))
        lines = current.splitlines(keepends=True)
        headings = [(i, line) for i, line in enumerate(lines, 1) if re.match(r"^#{1,6} ", line)]
        if headings:
            print(ui("Sections détectées", "Detected sections"))
            for i, line in headings[:20]:
                print(f"{i:>4}  {line.strip()}")
        action = ask_choice(
            ui("Action (view, append, replace, back)", "Action (view, append, replace, back)"),
            "view", select(("view", "append", "replace", "back")),
        )
        if action == "view":
            for i, line in enumerate(lines, 1):
                print(f"{i:>4}  {line.rstrip()}")
            action = ask_choice(
                ui("Action (append, replace, back)", "Action (append, replace, back)"),
                "back", select(("append", "replace", "back")),
            )
        if action == "back":
            continue
        if action == "replace" and not lines:
            print(ui("Le fichier est vide. Choisis append.", "The file is empty. Choose append."))
            continue
        if action == "replace":
            first = ask_choice(ui("Première ligne à remplacer", "First line to replace"), 1, bounded(1, len(lines)))
            last = ask_choice(ui("Dernière ligne à remplacer", "Last line to replace"), first, bounded(first, len(lines)))
        else:
            first = len(lines) + 1
            last = len(lines)
        print(ui("Saisis le nouveau texte. Termine par une ligne contenant uniquement :end.",
                 "Enter the new text. Finish with a line containing only :end."))
        replacement = []
        newline = "\r\n" if "\r\n" in current else "\n"
        while (line := input()) != ":end":
            replacement.append(line + newline)
        if action == "append" and replacement and current and not current.endswith(("\r", "\n")):
            replacement.insert(0, newline)
        updated = "".join(lines[:first - 1] + replacement + lines[last:])
        if updated == previous:
            changes.pop(relative, None)
        else:
            changes[relative] = (previous, updated)


def write_change(root, relative, previous, content):
    path = safe_path(root, relative)
    if read_existing(root, relative) != previous:
        raise ValueError(ui("Fichier modifié depuis l'aperçu : {0}", 'File changed since preview: {0}').format(relative))
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as temporary:
        temp_path = Path(temporary.name)
        try:
            temporary.write(content)
            temporary.close()
            if previous is None:
                os.link(temp_path, path)
            else:
                temp_path.chmod(path.stat().st_mode & 0o777)
                os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)


def parser():
    cli = argparse.ArgumentParser(description=ui(
        "Initialiser un workflow agentique local.", "Initialize a local agent workflow."
    ))
    commands = cli.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help=ui('Préparer un workflow agentique', 'Initialize an agent workflow'))
    init.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    mode = init.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help=ui('Appliquer après affichage du diff', 'Apply after showing the diff'))
    mode.add_argument("--dry-run", action="store_true", help=ui('Afficher le diff uniquement', 'Show the diff only'))
    init.add_argument("--non-interactive", action="store_true")
    init.add_argument("--tool", action="append", choices=TOOLS,
                      help=ui("Outil agentique, option répétable", "Agent tool, repeatable"))
    init.add_argument("--context-notes",
                      help=ui("Compléments au contexte généré", "Additional notes for the generated context"))
    init.add_argument("--ui-language", choices=("fr", "en"),
                      help=ui("Langue de la CLI", "CLI language"))
    init.add_argument("--docs-language", choices=("fr", "en"),
                      help=ui("Langue des fichiers générés", "Generated file language"))
    init.add_argument("--response-language", choices=("fr", "en"),
                      help=ui("Langue des réponses du LLM", "LLM response language"))
    init.add_argument("--language", action="append", help=ui('Langage, option répétable', 'Programming language, repeatable'))
    for field in ("goal", "audience", "first-result", "constraints", "test-rules"):
        init.add_argument(f"--{field}")
    init.add_argument("--detail", type=bounded(1, 10))
    for field in ("tests", "git"):
        init.add_argument(f"--{field}", type=bounded(0, 10))
    init.add_argument("--git-policy", choices=("manual", "undecided"), default="manual")
    init.add_argument("--commit-template")
    init.add_argument("--review-template")
    init.add_argument("--test-strategy", choices=("tdd", "after", "custom"))
    init.add_argument("--coverage", type=bounded(0, 100))
    init.add_argument("--coverage-scope", choices=("global", "changed"))
    return cli


def configure_languages(args, interactive):
    global ui
    choose = select(("fr", "en"))
    if args.ui_language is None:
        args.ui_language = ask_choice(
            "Langue du questionnaire / Questionnaire language (fr, en)", "fr", choose
        ) if interactive else "fr"
    ui = translator(args.ui_language)
    if args.docs_language is None:
        args.docs_language = ask_choice(
            ui("Langue des fichiers générés (fr, en)", "Generated file language (fr, en)"),
            args.ui_language, choose,
        ) if interactive else args.ui_language
    if args.response_language is None:
        args.response_language = ask_choice(
            ui("Langue des réponses du LLM (fr, en)", "LLM response language (fr, en)"),
            args.ui_language, choose,
        ) if interactive else args.ui_language


def configure_tools(args, interactive):
    if args.tool is not None:
        return
    if not interactive:
        args.tool = ["portable"]
        return

    def parse(value):
        return [select(TOOLS)(item.strip().lower()) for item in value.split(",")]

    args.tool = ask_choice(
        ui("Outils utilisés, séparés par des virgules (portable, codex, copilot, claude-code)",
           "Tools to use, separated by commas (portable, codex, copilot, claude-code)"),
        "portable", parse,
    )


def main():
    global ui
    language_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    language_parser.add_argument("--ui-language", choices=("fr", "en"))
    language_args, _ = language_parser.parse_known_args()
    ui = translator(language_args.ui_language)
    cli = parser()
    args = cli.parse_args()
    interactive = sys.stdin.isatty() and not args.non_interactive
    configure_languages(args, interactive)
    configure_tools(args, interactive)
    root = args.path.resolve()
    if not root.is_dir():
        cli.error(ui('Dossier introuvable : {0}', 'Directory not found: {0}').format(root))
    root_inventory = inventory(root)
    components = sorted(
        path for path in root.iterdir()
        if not path.name.startswith(".") and not path.is_symlink()
        and path.is_dir() and (path / ".git").exists()
    )
    languages, commands, evidence, populated, description = root_inventory
    files = harness_files(root, components)
    populated = populated or bool(components)
    if files:
        print(ui("Contexte ou harness détecté.", "Existing context or harness detected."))
        for relative in files:
            print(f"- {relative}")
    elif populated:
        print(ui("Projet existant sans harness détecté.", "Existing project with no detected harness."))
    else:
        print(ui("Dossier vide ou sans fichiers de projet détectés.", "Empty directory or no project files detected."))
    for label, values in (
        (ui("Langages détectés", "Detected languages"), languages),
        (ui("Commandes détectées", "Detected commands"), commands),
        (ui("Fichiers repérés", "Files detected"), evidence),
    ):
        if values:
            print(f"{label}: {', '.join(values)}")
    goal = summarize_project(root, files, description) if populated or files else ""
    action = "complete"
    if files and interactive:
        action = ask_choice(
            ui("Y a-t-il des corrections ou des compléments ? (edit = modifier, complete = compléter le socle, skip = quitter)",
               "Any corrections or additions? (edit = edit files, complete = fill gaps, skip = exit)"),
            "skip", select(("edit", "complete", "skip")),
        )
    if action == "skip":
        return
    if action == "edit":
        changes = edit_harness(root, files)
    else:
        if interactive and populated and not files and args.context_notes is None:
            args.context_notes = ask(ui(
                "Quel point veux-tu corriger ou ajouter à cette synthèse ? (Entrée pour passer)",
                "What would you like to correct or add to this summary? (Enter to skip)",
            ))
        configure(args, languages, interactive, populated or bool(files), goal)
        changes = plan(root, args, root_inventory, components)
    if args.tests == 0 and any(
        value is not None for value in (args.test_strategy, args.test_rules, args.coverage, args.coverage_scope)
    ):
        cli.error(ui('Les options de stratégie et de couverture nécessitent --tests entre 1 et 10.', 'Test strategy and coverage options require --tests between 1 and 10.'))
    if not changes:
        print(ui('Aucun changement. Utiliser update-context pour faire évoluer les fichiers existants.', 'No changes. Use update-context to update the existing files.'))
        return
    for relative, (previous, content) in changes.items():
        print("".join(difflib.unified_diff(
            (previous or "").splitlines(keepends=True), content.splitlines(keepends=True),
            fromfile=relative if previous is not None else "/dev/null", tofile=relative,
        )), end="")
    confirmed = args.apply
    if interactive and not args.dry_run and not confirmed:
        answers = ui({"o", "oui"}, {"y", "yes"})
        confirmed = ask(ui("Appliquer ? [o/N]", "Apply? [y/N]")).lower() in answers
    if confirmed:
        for relative, (previous, content) in changes.items():
            write_change(root, relative, previous, content)
        print(ui('{0} fichier(s) écrit(s).', 'Files written: {0}.').format(len(changes)))
    else:
        print(ui('Aperçu uniquement. Ajouter --apply pour écrire les fichiers.', 'Preview only. Add --apply to write the files.'))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, EOFError, KeyboardInterrupt) as error:
        print(ui("Initialisation interrompue. {0}", "Initialization interrupted. {0}").format(error),
              file=sys.stderr)
        sys.exit(1)
