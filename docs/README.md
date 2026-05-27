# Reflective Autonomy Annotation Console

This is a buildless static web app for turn-level annotation of reflective autonomy erosion (RAE). It can be served directly by GitHub Pages from the `docs/` directory.

## Features

- Background anonymous connection through Firebase Authentication
- Shared Firestore project workspace for multiple annotators
- Annotator ID field for retrieving the same annotator's saved work across sessions
- JSON, JSONL, NDJSON, and CSV case import from retained conversation exports
- Turn-level coding for `Rt`, `Ct`, `Vt`, `Gt`, `It`, `Mt`, and `At+1`
- Conversation-level mechanism, confidence, voluntary transfer, and reflective erosion flags
- Firestore save/load per annotator
- JSON export of all annotations in the current project

## Firebase Setup

1. Create a Firebase project.
2. Enable **Authentication > Sign-in method > Anonymous**.
3. Enable **Firestore Database**.
4. Add your GitHub Pages domain to **Authentication > Settings > Authorized domains**.
5. Apply rules based on `firebase-rules.example`.
6. Create a web app in Firebase and copy its config object.

For GitHub Pages, this repository serves the committed static app from `docs/`.
The Firebase web config lives at `docs/firebase-config.js`.

The Firebase web config is not a server secret, but GitHub secret scanning may flag API-key-shaped values. Access control should be enforced with Firebase Auth and Firestore rules.

If the app is open to unfamiliar annotators, do not rely on hidden UI controls for protection. Firestore rules should enforce who can import cases, read annotations, and write annotations.

Anonymous Auth is only a lightweight Firebase session. The app stores a user-entered `annotatorId` on each annotation so annotators can retrieve their existing labels by entering the same ID later. This is convenient for open annotation, but it is not a strong identity system: anyone who knows an annotator ID could attempt to use that ID. Use Google, email, or another real sign-in method if annotator identity needs to be protected.

## GitHub Pages Deployment

This app is placed under `docs/` and is designed for GitHub Pages branch deployment.

1. Open repository **Settings > Pages**.
2. Set **Source** to **Deploy from a branch**.
3. Set **Branch** to `main` and folder to `/docs`.
4. Save the Pages settings.
5. Open the published Pages URL after GitHub finishes the Pages build.

## Data Model

Firestore paths:

```text
annotationProjects/{projectId}/cases/{caseId}
annotationProjects/{projectId}/annotations/{caseId}_{annotatorId}
```

The import flow accepts rows with any of these common shapes:

- `conversation.turns`
- WildChat retained full-context rows with `case`, `screening`, and `conversation.turns`
- ShareGPT-style `conversations` arrays with `from`/`value`
- OpenAI-style `messages` arrays with `role`/`content`
- `case.turns`
- root-level `turns`
- prompt-response rows with `prompt`/`response`, `instruction`/`output`, or `input`/`answer`
- transcript rows with `conversation_text` containing `USER:` and `ASSISTANT:` markers

Each turn should contain a recognizable role (`user`, `assistant`, `human`, `gpt`) and text/content.

## Recommended Workflow

1. Use the bundled WildChat RAE v2 positive/borderline review set, or export another pilot set as JSONL.
2. Load the annotation app.
3. Set a shared project ID, such as `wildchat-rae-v2-positive-review`.
4. Enter your own annotator ID, such as `coder-01`.
5. One project owner imports the cases.
6. Each annotator loads the same project ID, enters their own annotator ID, and annotates independently.
7. To retrieve existing work, reload the same project with the same annotator ID.
8. Export annotations for adjudication and reliability analysis.

## Bundled WildChat RAE v2 Review Set

The app includes `wildchat_rae_v2_positive_review_cases.json`, generated from:

```text
data/autonomy_seed_cases/wildchat_rae_v2_screened_results.jsonl
```

It contains the 39 unique positive/borderline review cases selected by any of:

- `keep_for_rae`
- `keep_for_main_analysis`
- `keep_for_manual_review`
- `decision_oriented_score == 3`
- `risk_level in {medium, high}`

If the loaded Firestore project has no `cases` documents, the app automatically falls back to this bundled set. With the default three annotators, each case receives two reviewers and each annotator receives 26 cases.

The bundled cases also include LLM screening hints on user turns when available: `UIS`, `CES`, preference stability, utterance summary, rationale, and evidence snippets. These are displayed as reference material only; they do not prefill the human annotation fields.
