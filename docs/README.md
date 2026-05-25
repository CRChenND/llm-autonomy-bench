# Reflective Autonomy Annotation Console

This is a buildless static web app for turn-level annotation of reflective autonomy erosion (RAE). It can be served directly by GitHub Pages from the `docs/` directory.

## Features

- Google sign-in through Firebase Authentication
- Shared Firestore project workspace for multiple annotators
- JSON/JSONL case import from retained conversation exports
- Turn-level coding for `Rt`, `Ct`, `Vt`, `Gt`, `It`, `Mt`, and `At+1`
- Conversation-level mechanism, confidence, voluntary transfer, and reflective erosion flags
- Firestore save/load per annotator
- JSON export of all annotations in the current project

## Firebase Setup

1. Create a Firebase project.
2. Enable **Authentication > Sign-in method > Google**.
3. Enable **Firestore Database**.
4. Add your GitHub Pages domain to **Authentication > Settings > Authorized domains**.
5. Apply rules based on `firebase-rules.example`.
6. Create a web app in Firebase and copy its config object.

This repository currently includes a default Firebase web config for the `llm-autonomy` Firebase project. To use a different Firebase project, paste its config JSON into the app's Firebase panel:

```json
{
  "apiKey": "...",
  "authDomain": "...firebaseapp.com",
  "projectId": "...",
  "storageBucket": "...",
  "messagingSenderId": "...",
  "appId": "..."
}
```

The Firebase web config is not a secret. Access control should be enforced with Firebase Auth and Firestore rules.

If the app is open to unfamiliar annotators, do not rely on hidden UI controls for protection. Firestore rules should enforce who can import cases, read annotations, and write annotations.

## GitHub Pages Deployment

This app is already placed under `docs/`, which GitHub Pages supports without a build step.

1. Push the repository to GitHub.
2. Open repository **Settings > Pages**.
3. Set **Source** to the branch you use, and **Folder** to `/docs`.
4. Save and open the published Pages URL.

## Data Model

Firestore paths:

```text
annotationProjects/{projectId}/cases/{caseId}
annotationProjects/{projectId}/annotations/{caseId}_{annotatorUid}
```

The import flow accepts rows with any of these common shapes:

- `conversation.turns`
- `case.turns`
- root-level `turns`
- root-level OpenAI-style `messages`

Each turn should contain a recognizable role (`user`, `assistant`, `human`, `gpt`) and text/content.

## Recommended Workflow

1. Export or prepare a pilot set as JSONL.
2. Load the annotation app and sign in.
3. Set a shared project ID, such as `pilot-v1`.
4. One project owner imports the cases.
5. Each annotator signs in, loads the same project ID, and annotates independently.
6. Export annotations for adjudication and reliability analysis.
