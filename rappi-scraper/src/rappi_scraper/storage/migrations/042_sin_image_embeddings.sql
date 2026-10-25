-- Los vectores de las fotos (`image_embeddings`, de la 010) nunca se usaron: la búsqueda y Mochi trabajan solo con el
-- texto y ningún código lee ni escribe esta tabla. Se borra con lo que tenga.
DROP TABLE IF EXISTS image_embeddings;
