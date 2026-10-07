# Prix des Kamas — version app Android (PWA)

Cette version n'a besoin d'aucun PC allume : un robot gratuit de GitHub va
chercher les prix toutes les ~5 minutes, et ton telephone installe une
icone comme une vraie app. Gratuit, pas de serveur a payer.

## 1. Creer le depot GitHub (une fois)

1. Va sur https://github.com et cree un compte si besoin (gratuit).
2. Clique "New repository". Nomme-le par exemple `kamas-prices`. Mets-le
   en **Public** (necessaire pour GitHub Pages gratuit). Cree-le vide
   (sans README).
3. Sur ta machine, dans le dossier `kamas-pwa` (celui-ci), ouvre un
   terminal et lance :

```
git init
git add .
git commit -m "Premiere version"
git branch -M main
git remote add origin https://github.com/TON-NOM-UTILISATEUR/kamas-prices.git
git push -u origin main
```

(Remplace `TON-NOM-UTILISATEUR` par ton pseudo GitHub.)

## 2. Activer GitHub Pages

1. Sur la page du depot, va dans **Settings > Pages**.
2. Source : "Deploy from a branch" -> Branche `main`, dossier `/ (root)`.
3. Enregistre. Au bout d'une minute ou deux, GitHub te donne une URL du
   style `https://TON-NOM-UTILISATEUR.github.io/kamas-prices/`.

## 3. Verifier que le robot tourne

1. Va dans l'onglet **Actions** du depot. Tu dois voir le workflow
   "Update kamas prices".
2. Clique dessus, puis "Run workflow" pour le lancer une premiere fois
   manuellement (sinon il attend le prochain creneau de 5 minutes).
3. S'il reussit (coche verte), `prices.json` est mis a jour dans le
   depot automatiquement toutes les ~5 minutes, indefiniment, sans que
   tu touches a rien.

## 4. Installer l'icone sur ton Android

1. Ouvre l'URL `https://TON-NOM-UTILISATEUR.github.io/kamas-prices/`
   dans **Chrome** sur ton telephone Android.
2. Menu (les trois points en haut a droite) -> "Ajouter a l'ecran
   d'accueil" (ou Chrome te propose directement une bannière
   d'installation).
3. Confirme. Une icone "Kamas" apparait sur ton telephone, s'ouvre en
   plein ecran comme une vraie app.

## Données suivies

Le robot récupère maintenant les prix en MAD/DH par million et le statut de stock pour quatre sites : iBendouma, LesKamas, VenteKamas et TryAndJudge. Pour VenteKamas, le prix utilisé est celui du virement bancaire au Maroc.

## Limites a connaitre

- GitHub Actions ne garantit pas exactement 5 minutes — selon la charge
  de GitHub, ca peut parfois prendre un peu plus longtemps. C'est gratuit
  et automatique, mais pas a la seconde pres.
- Si iBendouma, LesKamas ou VenteKamas changent la structure de leur
  page, le script peut rater certains prix jusqu'a ce qu'on l'ajuste —
  regarde l'onglet Actions de temps en temps pour voir si tout va bien.
- Sur iPhone, l'installation en icone existe aussi (Safari > Partager >
  "Sur l'ecran d'accueil") mais l'experience est un peu plus limitee
  qu'Android.
