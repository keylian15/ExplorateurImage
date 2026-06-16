Voici la démonstration de l'application suivant un fil conducteur ainsi que l'explication des features au fur et a mesures. 

Vous etes un photographe, vous avez dans votre disque 41 000 images mais vous ne les avez pas rangés ni renommé. 
Vous devez retrouver cette image et les images similaires:

![Image a retrouver](../Images/A_Retrouver.jpg)

Dans un premier temps il faut ouvrir le dossier correspondant a votre disque, et lancer l'auto complétion sur toutes les images. (Ou le faire a la main.)
Si une image est déjà traité comme celle ci alors elle a une pastille verte. ![Image Indéxé](../Images/Image_Indexe.png)

** Details : Pour afficher autant d'images j'ai mis en place un system de thumbnails pour ne pas surcharger l'affichage, un affichage dynamique en fonction de ce qu'on voit sur l'ecran, et un LRU Cache Memoire. 
J'ai utilisé l'amélioration visuel 

L'auto complétion va parcourir chaque images, les envoyer ollama pour obtenir une description ainsi que des mots clés.

** DETAILS : L'auto complétion boucle sur l'entierté du dossier en asyncrhone. Il ne réindexe pas les images déjà indéxé et sauvegarde l'index ainsi que l'embedding généré en meme temps. 

Pour voir ce qu'est le description d'image il suffit de clic gauche sur l'image. Vous pouvez également faire votre propre description avec les mots clés. ![Details Image](../Images/Details_Image.png)

(Avec un clic droit on a une vue plus grande de l'image et d'autre utilisations qu'on verra plus bas)

Vous pourrez chercher une image qui ressemble de près ou de loin a l'image rechercher parmis les images indéxés puis naviguer par ses voisins mais ca serait très long. 

** Details : Les k-voinsins fonctionnent par similarité cosinus de l'embedding donc il triera que les images indéxés. 

On peut donc essayer d'avoir une vue d'ensemble sur le corpus via l'onglet carte 2D. Qui est une réprensentation de notre dossier d'images indexé. 

![MAP2D](../Images/MAP2D.png)

Différents paramétres peuvent etre modifier pour changer le visuel de la map ![PARAM MAP_2D](../Images/Param_2DMAP.png)

(QUESTION : La description des params est déjà en tooltips je la rajoute quand meme ? )

** Details : La map utilise UMAP pour passer l'embedding de dimensions 768 a 2. Puis j'utilise HDBSCAN pour la séparation en culster et enfin qwen2.5vl:7b avec un nombre d'image aléatoire pour qu'il nomme le cluster. 

On pourrait chercher un cluster qui correspond a notre thème sur l'image a savoir groupe hivernal / montagne. puis fouiller dans ce cluster. C'est fonctionnel et moins longs que de juste fouiller dans le dossier. 

C'est donc la que la recherche est très utile. On peut chercher un mot clé en francais. Cela marche sur la map ou sur la gallerie. 
Prenons la gallerie et recherchons montagne par exemple. 
![Recherche Gallerie Montagne](../Images/Recherche_Gallerie.png)
Nous avons des images en lien avec la montagne. 

** Details : La recherche est la même que les k-voinsins avec l'embedding de la recherche.

Si nous voulons pas perdre les recherches qu'on a fait nous avons plusieurs possiblités. 
La premiere est d'épingler les images qui nous sembles importantes pour pas les perdres. ![Image Epinglé](../Images/Recherche_Gallerie_Epingle.png)

La seconde est d'enregistrer la recherche ce qui permettera de revenir par la suite a cette recherche et de naviguer entre elles.

** DETAILS : L'historique est un Arbre qui prend en node la recherche et les noms des images résultantes de la recherche. L'affinage se base sur les résultats de la précédente requete comme base.

![Historique](../Images/Recherche_Gallerie_Historique.png)

L'affinage est possible, et pratique dans notre cas car on recherche des personnes en montagnes avec une croix. Donc nous pouvons faire plusieurs affinage en fonction des résultats. On peut affiner montagne pour mettre personnes puis croix ou meme faire d'autre branche. La navigation entre elle permet de vite voir le meilleur résultat.

![Affinage](../Images/Recherche_Gallerie_Affinage.png)

La recherche n'est pas uniquement par mot clés, vous pouvez ecrire une phrase.
![Phrase dans la recherche](../Images/Recherche_Gallerie_Phrase.png)

** DETAILS : Cela fonctionne car c'est de la recherche par embedding.

Lorsque vous selectionner l'image dans la gallerie elle sera selectionner egalement dans la map ce qui permet d'avoir un visuel sur son cluster. 


Maintenant qu'on a l'image voulu il faut les images similaires. On pourrait regarder les k-voinsins mais nous allons utiliser autre chose. 

Le clic droit permet de voir l'image en gros plan et meilleur qualité mais surtout d'avoir accès au panel de sam3.

** DETAILS : Pour les images agrandi j'utilise les images orignal améliorer comme fait windows explorer avec device Ratio etc. 

SAM3 est une IA de Méta qui permet de faire de la recherche sur des images. 
![SAM3](../Images/SAM3.png)

3 différents zones sont présentes : La semgentation dans l'image qui permet de reperer plusieurs meme objet, on peut soit le faire par recherche textuel en anglais (car sam3 est en anglais) soit par box en dessinant sur l'image.

Par exemple sur notre image on peut marquer "person" (ou tout autre mot clés) ou dessiner sur une personne. la confiance est le minimum pour que le resultat soit affiché, si la confiance est bas alors beaucoup plus de box (parfois qui n'ont pas de rapport) seront affiché. 

La recherche dans le dossier est la fonctionnalité la plus utile ici. car elle permet d'analyser l'entierté du dossier des images indéxé mais celle non indéxé également. 

Trois méthodes sont proposés : 
Embbeding la plus rapide : on va demander a qwenn2.5vl ce qu'il voit sur la zone selectionner par sam3, puis faire une recherche comme la barre de recherche, c'est très rapide et se base sur les images indéxés. Le parametre de seuil embedding est important plus il est bas plus les résultat seront eloingnés de la recherche

SAM3 simple qui est precis et plus long : on va aussi demander a qwenn2.5vl la description de la zone mais cette fois on va parcourir chaque image du dossier demander a sam3 de donner les resultats pour la description en prompt, si le resutat n'est pas au dessus de la confiance donnée alors on ne le garde pas. Il se base sur tout le dossier d'image indéxé ou non

Enfin l'hybride, il fait comme sam3 simple sauf qu'avant de rendre les images il verifie avec l'embedding. Il n'est pas forcément plus long mais il est plus prècis. 

![Segmentation](../Images/SAM3_Segmentation_Image.png)
** Details la lenteur dépend de deux choses : l'appel a qwenn2.5vl et l'appel a sam3 par image. 

La checkbox attendre la fin est utile seulement si vous voulez les résultats par ordre de correspondance. 

Donc dans notre cas si on utilise la premiere méthode avec la recherche par box on obtient 207 résultats.
![SEGMENTATION RESULTAT](../Images/SAM3_Segmentation_Resultat.png)
Il est possible de cliquer sur les images et d'enchainer les recherches etc. 


** DETAILS : L'affichage des résultats peut etre gros donc l'affichage est en asynchrone. Comme la rechercher pour ne pas paralyser l'application. 

Un onglet parametre permet de modifier le théme de l'application mais aussi la langue. si vous avez besoin de faire montrer a d'autre personne non francaise. 

![Settings](../Images/Settings1.png) ![Settings](../Images/Settings2.png)