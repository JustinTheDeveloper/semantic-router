from typing import List, Optional, Tuple, Dict

import numpy as np
from numpy.linalg import norm

from semantic_router.schema import ConfigParameter, SparseEmbedding, Utterance
from semantic_router.index.local import LocalIndex
from semantic_router.utils.logger import logger
from typing import Any


class HybridLocalIndex(LocalIndex):
    type: str = "hybrid_local"
    sparse_index: Optional[list[dict]] = None
    route_names: Optional[np.ndarray] = None

    def __init__(self):
        super().__init__()

    def add(
        self,
        embeddings: List[List[float]],
        routes: List[str],
        utterances: List[str],
        function_schemas: Optional[List[Dict[str, Any]]] = None,
        metadata_list: List[Dict[str, Any]] = [],
        sparse_embeddings: Optional[List[SparseEmbedding]] = None,
    ):
        if sparse_embeddings is None:
            raise ValueError("Sparse embeddings are required for HybridLocalIndex.")
        if function_schemas is not None:
            logger.warning("Function schemas are not supported for HybridLocalIndex.")
        if metadata_list:
            logger.warning("Metadata is not supported for HybridLocalIndex.")
        embeds = np.array(
            embeddings
        )  # TODO: we previously had as a array, so switching back and forth seems inefficient
        routes_arr = np.array(routes)
        if isinstance(utterances[0], str):
            utterances_arr = np.array(utterances)
        else:
            utterances_arr = np.array(
                utterances, dtype=object
            )  # TODO: could we speed up if this were already array?
        if self.index is None or self.sparse_index is None:
            self.index = embeds
            self.sparse_index = [
                x.to_dict() for x in sparse_embeddings
            ]  # TODO: switch back to using SparseEmbedding later
            self.routes = routes_arr
            self.utterances = utterances_arr
        else:
            # TODO: we should probably switch to an `upsert` method and standardize elsewhere
            self.index = np.concatenate([self.index, embeds])
            self.sparse_index.extend([x.to_dict() for x in sparse_embeddings])
            self.routes = np.concatenate([self.routes, routes_arr])
            self.utterances = np.concatenate([self.utterances, utterances_arr])

    def get_utterances(self) -> List[Utterance]:
        """Gets a list of route and utterance objects currently stored in the index.

        Returns:
            List[Tuple]: A list of (route_name, utterance) objects.
        """
        if self.routes is None or self.utterances is None:
            return []
        return [Utterance.from_tuple(x) for x in zip(self.routes, self.utterances)]

    def describe(self) -> Dict:
        return {
            "type": self.type,
            "dimensions": self.index.shape[1] if self.index is not None else 0,
            "vectors": self.index.shape[0] if self.index is not None else 0,
        }

    def _sparse_dot_product(
        self, vec_a: dict[int, float], vec_b: dict[int, float]
    ) -> float:
        # switch vecs to ensure first is smallest for more efficiency
        if len(vec_a) > len(vec_b):
            vec_a, vec_b = vec_b, vec_a
        return sum(vec_a[i] * vec_b.get(i, 0) for i in vec_a)

    def _sparse_index_dot_product(self, vec_a: dict[int, float]) -> list[float]:
        if self.sparse_index is None:
            raise ValueError("self.sparse_index is not populated.")
        dot_products = [
            self._sparse_dot_product(vec_a, vec_b) for vec_b in self.sparse_index
        ]
        return dot_products

    def query(
        self,
        vector: np.ndarray,
        top_k: int = 5,
        route_filter: Optional[List[str]] = None,
        sparse_vector: dict[int, float] | SparseEmbedding | None = None,
    ) -> Tuple[np.ndarray, List[str]]:
        """Search the index for the query and return top_k results.

        :param vector: The query vector to search for.
        :type vector: np.ndarray
        :param top_k: The number of top results to return, defaults to 5.
        :type top_k: int, optional
        :param route_filter: A list of route names to filter the search results, defaults to None.
        :type route_filter: Optional[List[str]], optional
        :param sparse_vector: The sparse vector to search for, must be provided.
        :type sparse_vector: dict[int, float]
        """
        if route_filter:
            raise ValueError("Route filter is not supported for HybridLocalIndex.")

        xq_d = vector.copy()
        # align sparse vector type
        if isinstance(sparse_vector, SparseEmbedding):
            xq_s = sparse_vector.to_dict()
        elif isinstance(sparse_vector, dict):
            xq_s = sparse_vector
        else:
            raise ValueError("Sparse vector must be a SparseEmbedding or dict.")

        if self.index is not None and self.sparse_index is not None:
            # calculate dense vec similarity
            index_norm = norm(self.index, axis=1)
            xq_d_norm = norm(xq_d)  # TODO: this used to be xq_d.T, should work without
            sim_d = np.squeeze(np.dot(self.index, xq_d.T)) / (index_norm * xq_d_norm)
            # calculate sparse vec similarity
            sim_s = np.array(self._sparse_index_dot_product(xq_s))
            total_sim = sim_d + sim_s
            # get indices of top_k records
            top_k = min(top_k, total_sim.shape[0])
            idx = np.argpartition(total_sim, -top_k)[-top_k:]
            scores = total_sim[idx]
            # get the utterance categories (route names)
            route_names = self.routes[idx] if self.routes is not None else []
            return scores, route_names
        else:
            logger.warning("Index or sparse index is not populated.")
            return np.array([]), []

    async def aquery(
        self,
        vector: np.ndarray,
        top_k: int = 5,
        route_filter: Optional[List[str]] = None,
        sparse_vector: dict[int, float] | SparseEmbedding | None = None,
    ) -> Tuple[np.ndarray, List[str]]:
        """Search the index for the query and return top_k results. This method calls the
        sync `query` method as everything uses numpy computations which is CPU-bound
        and so no benefit can be gained from making this async.

        :param vector: The query vector to search for.
        :type vector: np.ndarray
        :param top_k: The number of top results to return, defaults to 5.
        :type top_k: int, optional
        :param route_filter: A list of route names to filter the search results, defaults to None.
        :type route_filter: Optional[List[str]], optional
        :param sparse_vector: The sparse vector to search for, must be provided.
        :type sparse_vector: dict[int, float]
        """
        return self.query(
            vector=vector,
            top_k=top_k,
            route_filter=route_filter,
            sparse_vector=sparse_vector,
        )

    def aget_routes(self):
        logger.error(f"Sync remove is not implemented for {self.__class__.__name__}.")

    def _write_config(self, config: ConfigParameter):
        logger.warning(f"No config is written for {self.__class__.__name__}.")

    def delete(self, route_name: str):
        """
        Delete all records of a specific route from the index.
        """
        if (
            self.index is not None
            and self.routes is not None
            and self.utterances is not None
        ):
            delete_idx = self._get_indices_for_route(route_name=route_name)
            self.index = np.delete(self.index, delete_idx, axis=0)
            self.routes = np.delete(self.routes, delete_idx, axis=0)
            self.utterances = np.delete(self.utterances, delete_idx, axis=0)
        else:
            raise ValueError(
                "Attempted to delete route records but either index, routes or "
                "utterances is None."
            )

    def delete_index(self):
        """
        Deletes the index, effectively clearing it and setting it to None.
        """
        self.index = None
        self.routes = None
        self.utterances = None

    def _get_indices_for_route(self, route_name: str):
        """Gets an array of indices for a specific route."""
        if self.routes is None:
            raise ValueError("Routes are not populated.")
        idx = [i for i, route in enumerate(self.routes) if route == route_name]
        return idx

    def __len__(self):
        if self.index is not None:
            return self.index.shape[0]
        else:
            return 0
