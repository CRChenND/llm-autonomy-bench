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

For deployed GitHub Pages, add the config JSON as a repository secret named `FIREBASE_CONFIG_JSON`:

```text
GitHub repo → Settings → Secrets and variables → Actions → New repository secret
Name: FIREBASE_CONFIG_JSON
Value: the Firebase web config JSON
```

Use strict JSON, without `const firebaseConfig =`:

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

The deployment workflow generates `docs/firebase-config.js` during the Pages build. That generated file is not committed to the repository.

For local development, either paste the config JSON into the app's Firebase panel or create a local, ignored file at `docs/firebase-config.js` based on `docs/firebase-config.example.js`.

The Firebase web config is not a server secret, but GitHub secret scanning may flag API-key-shaped values. Keep project configs out of committed source files. Access control should be enforced with Firebase Auth and Firestore rules.

If the app is open to unfamiliar annotators, do not rely on hidden UI controls for protection. Firestore rules should enforce who can import cases, read annotations, and write annotations.

## GitHub Pages Deployment

This app is placed under `docs/`. The repository includes `.github/workflows/deploy-pages.yml`, which deploys the app to GitHub Pages and injects `firebase-config.js` from the `FIREBASE_CONFIG_JSON` repository secret.

1. Add the `FIREBASE_CONFIG_JSON` repository secret.
2. Open repository **Settings > Pages**.
3. Set **Source** to **GitHub Actions**.
4. Push to `main` or run the **Deploy GitHub Pages** workflow manually.
5. Open the published Pages URL.

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
