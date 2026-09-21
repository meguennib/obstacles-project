# Backend API

Ce projet est une API Backend développée avec **FastAPI** pour le calcul d'itinéraires et la gestion d'événements de circulation (fermetures de routes). Il s'appuie sur **PostgreSQL** avec **PostGIS** et **pgRouting**.

Il fonctionne de concert avec le frontend situé dans `../frontend/`.

## Structure du Projet Backend

```
backend/
├── app/
│   ├── apps/
│   │   ├── events/             # Module de gestion des événements (fermetures de routes)
│   │   │   ├── api.py          # Endpoints API (création, validation, liste, désactivation)
│   │   │   ├── schemas.py      # Modèles Pydantic (validation des données)
│   │   │   └── service.py      # Logique métier et requêtes SQL brutes
│   │   └── routing/            # Module de calcul d'itinéraires
│   │   │   ├── api.py          # Endpoint API pour le calcul de route
│   │   │   ├── schemas.py      # Modèles Pydantic pour les requêtes/réponses de routage
│   │   │   └── service.py      # Algorithme Dijkstra et exclusion dynamique des routes fermées
│   ├── core/
│   │   ├── config.py           # Configuration de l'application (variables d'environnement)
│   │   └── db.py               # Configuration de la base de données (Session, Engine)
│   └── main.py                 # Point d'entrée de l'application FastAPI
├── manage.py                   # Outil CLI pour l'administration et les tests (check-db, install-schema)
├── requirements.txt            # Liste des dépendances Python
└── .env                        # Variables d'environnement (non inclus dans le repo par défaut)
```

## Description des Fichiers Clés

### 1. Racine
- **`manage.py`** : Script utilitaire en ligne de commande (basé sur `typer`). Il permet de :
    - `check-db` : Vérifier la connexion à PostgreSQL, PostGIS et pgRouting.
    - `install-schema` : Installer ou mettre à jour les tables et index nécessaires.
    - `smoke-route` : Lancer un test rapide de routage et de fermeture de route pour valider le bon fonctionnement.
- **`requirements.txt`** : Contient toutes les librairies nécessaires (FastAPI, SQLAlchemy, Typer, Psycopg, etc.).

### 2. Dossier `app/`
- **`main.py`** : Initialise l'application `FastAPI`, configure le CORS (pour autoriser le frontend) et inclut les routeurs (`routing` et `events`).

### 3. Dossier `app/core/`
- **`config.py`** : Charge la configuration depuis le fichier `.env`.
- **`db.py`** : Gère la connexion à la base de données (`SessionLocal`).

### 4. Dossier `app/apps/events/` (Gestion des événements)
- **`api.py`** : Routes : `POST /road_closed` (créer), `POST .../validate`, `POST .../disable`, `GET /road_closed`.
- **`service.py`** : Logique SQL pour gérer `public.events_road_closed`.

### 5. Dossier `app/apps/routing/` (Calcul d'itinéraires)
- **`api.py`** : Route `POST /route`.
- **`service.py`** : Utilise `pgr_dijkstra` pour le calcul. Exclut dynamiquement les routes fermées (coût = -1).

## Installation et Lancement

1.  **Pré-requis** : Python 3.10+, PostgreSQL avec PostGIS et pgRouting activés.
2.  **Installation des dépendances** :
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configuration** :
    Créez un fichier `.env` à la racine avec vos accès BDD (voir `app/core/config.py`).
4.  **Initialisation BDD** :
    ```bash
    python manage.py check-db
    python manage.py install-schema
    ```
5.  **Lancement du serveur** :
    ```bash
    uvicorn app.main:app --reload
    ```
    L'API sera disponible sur `http://localhost:8000` (Documentation sur `/docs`).

6.  **Tests rapides** :
    ```bash
    python manage.py smoke-route
    ```
