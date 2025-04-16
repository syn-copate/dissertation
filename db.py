from typing import Union, List, Dict, Optional
from neo4j import GraphDatabase, Transaction, Result


class Neo4jDB:
    def __init__(
        self,
        uri: str = "neo4j://localhost:7687",
        user: str = "neo4j",
        password: str = "12345678",
        database: str = None,
    ):
        """
        :param database: 数据库名称（可选，社区版不需要）
        """
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database
        self._session = None
        self._transaction = None

    def close(self):
        self._driver.close()

    def execute_query(self, query: str, parameters: dict = None, **kwargs) -> Result:
        """
        执行Cypher查询的通用方法

        :param query: Cypher查询语句
        :param parameters: 查询参数字典
        :return: 查询结果
        """
        parameters = parameters or {}
        with self._driver.session(database=self._database) as session:
            result = session.run(query, parameters, **kwargs)
            return [result.single()]

    def create_node(
        self, labels: Union[str, List[str]], properties: dict = None
    ) -> dict:
        """
        创建节点

        :param label: 节点标签
        :param properties: 节点属性字典
        :return: 创建的节点信息
        """
        if isinstance(labels, str):
            labels = [labels]
        label_str = ":".join(labels)
        query = f"CREATE (n:{label_str} $props) RETURN n"
        result = self.execute_query(query, {"props": properties or {}})
        new_node = result[0]["n"]
        return self._convert_node(new_node)

    def merge_node(self, labels: Union[str, List[str]], properties: dict = None):
        """
        合并节点

        :param label: 节点标签
        :param properties: 节点属性字典
        :return: 创建的节点信息
        """
        if isinstance(labels, str):
            labels = [labels]
        label_str = ":".join(labels)
        prop_placeholders = ", ".join([f"{k}: ${k}" for k in properties.keys()])
        cypher = f"MERGE (n:{label_str} {{{prop_placeholders}}}) RETURN n"
        result = self.execute_query(cypher, properties)
        merged_node = result[0]["n"]
        return self._convert_node(merged_node)

    def match_nodes(
        self, labels: Union[str, List[str]], properties: dict = None, limit: int = None
    ) -> list[dict]:
        """
        查找匹配条件的节点

        :param label: 节点标签
        :param properties: 匹配属性字典
        :return: 匹配节点列表
        """
        if isinstance(labels, str):
            labels = [labels]
        label_str = ":".join(labels)
        where_clause = (
            "WHERE " + " AND ".join([f"n.{k} = ${k}" for k in properties.keys()])
            if properties
            else ""
        )
        limit_clause = f"LIMIT {limit}" if limit else ""
        query = f"MATCH (n:{label_str}) {where_clause} RETURN n {limit_clause}"
        result = self.execute_query(query, parameters=properties or {})
        return [self._convert_node(record["n"]) for record in result]

    def create_relationship(
        self, from_id: str, to_id: str, rel_type: str, properties: dict = None
    ) -> dict:
        """
        创建两个节点之间的关系

        :param from_id: 起始节点ID
        :param to_id: 目标节点ID
        :param rel_type: 关系类型
        :param properties: 关系属性
        :return: 创建的关系信息
        """
        query = (
            "MATCH (a), (b) "
            "WHERE elementId(a) = $from_id AND elementId(b) = $to_id "
            f"CREATE (a)-[r:{rel_type} $props]->(b) RETURN r"
        )
        result = self.execute_query(
            query, {"from_id": from_id, "to_id": to_id, "props": properties or {}}
        )
        return self._convert_relationship(result[0]["r"])

    def find_relationships(
        self,
        from_labels: Union[str, List[str]] = None,
        to_labels: Union[str, List[str]] = None,
        rel_type: str = None,
        properties: dict = None,
        limit: int = None,
    ) -> List[dict]:
        """
        查找匹配条件的关系（支持多标签节点）

        :param from_labels: 起始节点标签
        :param to_labels: 目标节点标签
        :param rel_type: 关系类型
        :param properties: 关系属性
        :param limit: 返回结果数量限制
        :return: 匹配关系列表
        """
        # 构建标签匹配部分
        from_label_str = self._build_label_match("a", from_labels)
        to_label_str = self._build_label_match("b", to_labels)
        rel_type_str = f":{rel_type}" if rel_type else ""

        # 构建WHERE条件
        where_parts = []
        if properties:
            where_parts.extend([f"r.{k} = ${k}" for k in properties.keys()])
        where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""

        limit_clause = f"LIMIT {limit}" if limit else ""

        query = (
            f"MATCH (a{from_label_str})-[r{rel_type_str}]->(b{to_label_str}) "
            f"{where_clause} RETURN r, a, b {limit_clause}"
        )

        result = self.execute_query(query, parameters=properties or {})
        return [
            {
                "relationship": self._convert_relationship(record["r"]),
                "from_node": self._convert_node(record["a"]),
                "to_node": self._convert_node(record["b"]),
            }
            for record in result
        ]

    def _build_label_match(
        self, alias: str, labels: Union[str, List[str], None]
    ) -> str:
        """构建标签匹配的Cypher片段"""
        if not labels:
            return ""

        if isinstance(labels, str):
            labels = [labels]

        return ":" + ":".join(labels)

    def update_node(
        self,
        element_id: str,
        properties: dict,
        add_labels: List[str] = None,
        remove_labels: List[str] = None,
    ) -> dict:
        """
        更新节点属性

        :param element_id: 要更新的节点ID
        :param properties: 要更新/添加的属性字典
        :param add_labels: 要添加的标签列表
        :param remove_labels: 要删除的标签列表
        :return: 更新后的节点信息
        """
        query_parts = ["MATCH (n) WHERE elementId(n) = $element_id"]

        if properties:
            query_parts.append("SET n += $props")

        # 添加标签
        if add_labels:
            add_labels_str = " ".join([f"SET n:{label}" for label in add_labels])
            query_parts.append(add_labels_str)

        # 删除标签
        if remove_labels:
            remove_labels_str = " ".join(
                [f"REMOVE n:{label}" for label in remove_labels]
            )
            query_parts.append(remove_labels_str)

        query_parts.append("RETURN n")
        # query = "MATCH (n) WHERE elementId(n) = $element_id SET n += $props RETURN n"
        query = " ".join(query_parts)
        result = self.execute_query(
            query, {"element_id": element_id, "props": properties or {}}
        )
        return self._convert_node(result[0]["n"])

    def delete_node(self, element_id: str):
        """删除节点及其所有关系"""
        query = "MATCH (n) WHERE elementId(n) = $element_id DETACH DELETE n"
        self.execute_query(query, {"element_id": element_id})

    def transaction(self) -> Transaction:
        """获取事务对象（配合with语句使用）"""
        self._session = self._driver.session(database=self._database)
        self._transaction = self._session.begin_transaction()
        return self._transaction

    def commit(self):
        """提交事务"""
        if self._transaction:
            self._transaction.commit()
            self._session.close()
            self._transaction = None
            self._session = None

    def rollback(self):
        """回滚事务"""
        if self._transaction:
            self._transaction.rollback()
            self._session.close()
            self._transaction = None
            self._session = None

    @staticmethod
    def _convert_node(node) -> dict:
        """将neo4j节点对象转换为字典"""
        return {
            "element_id": node.element_id,
            "labels": list(node.labels),
            "properties": dict(node),
        }

    @staticmethod
    def _convert_relationship(rel) -> dict:
        """将neo4j关系对象转换为字典"""
        return {
            "element_id": rel.element_id,
            "type": rel.type,
            "properties": dict(rel),
            "start_element_id": rel.nodes[0].element_id,
            "end_element_id": rel.nodes[1].element_id,
        }

    def copy_node_and_relations(self, element_id: str, update_props: dict = None):
        """
        复制节点标签、属性、相连关系

        :param element_id: 要复制的节点ID
        :param properties: 要更新/添加的属性字典
        :param add_labels: 要添加的标签列表
        :return: 复制的节点信息
        """
        with self._driver.session() as session:
            result = session.execute_write(
                self._copy_node_and_relations, element_id, update_props
            )
            return self._convert_node(result)

    @staticmethod
    def _copy_node_and_relations(tx, element_id: str, update_props: dict = None):
        # 获取原始节点属性
        node_result = list(
            tx.run(
                "MATCH (n) WHERE elementId(n) = $element_id RETURN n",
                element_id=element_id,
            )
        )

        if not node_result:
            raise ValueError(f"Node with elementId {element_id} not found")
        node_record = node_result[0]["n"]
        labels = list(node_record.labels)
        label_str = ":".join(labels)
        new_props = dict(node_record)
        new_props.update(update_props)
        # 创建新节点
        new_node_result = list(
            tx.run(
                f"CREATE (n:{label_str} $properties) RETURN n",
                properties=new_props,
            )
        )[0]["n"]
        new_element_id = new_node_result.element_id

        # 复制出向关系
        out_rels = list(
            tx.run(
                "MATCH (n)-[r]->(m) WHERE elementId(n) = $element_id "
                "RETURN type(r) as rel_type, properties(r) as rel_props, elementId(m) as target_id",
                element_id=element_id,
            )
        )
        for rel in out_rels:
            tx.run(
                "MATCH (src), (tgt) WHERE elementId(src) = $new_element_id AND elementId(tgt) = $target_id "
                f"CREATE (src)-[r:{rel["rel_type"]} $rel_props]->(tgt)",
                new_element_id=new_element_id,
                target_id=rel["target_id"],
                rel_props=rel["rel_props"] or {},
            )

        # 复制入向关系
        in_rels = list(
            tx.run(
                "MATCH (m)-[r]->(n) WHERE elementId(n) = $element_id "
                "RETURN type(r) as rel_type, properties(r) as rel_props, elementId(m) as source_id",
                element_id=element_id,
            )
        )
        for rel in in_rels:
            tx.run(
                "MATCH (src), (tgt) WHERE elementId(src) = $source_id AND elementId(tgt) = $new_element_id "
                f"CREATE (src)-[r:{rel['rel_type']} $rel_props]->(tgt)",
                source_id=rel["source_id"],
                new_element_id=new_element_id,
                rel_props=rel["rel_props"] or {},
            )

        return new_node_result


if __name__ == "__main__":
    db = Neo4jDB()
    try:
        # 自动提交事务示例
        node1 = db.create_node("Person", {"name": "Alice", "age": 30})
        node2 = db.create_node("Person", {"name": "Bob", "age": 25})
        print(node1, node2)

        # 创建关系
        rel = db.create_relationship(
            node1["element_id"], node2["element_id"], "KNOWS", {"since": "1989"}
        )
        print("Created relationship:", rel)

        # # 手动事务示例
        # tx = db.transaction()
        # try:
        #     new_node = tx.run(
        #         "CREATE (n:Test $props) RETURN n", {"props": {"test": True}}
        #     )[0]["n"]
        #     tx.commit()
        # except Exception as e:
        #     tx.rollback()
        #     raise

        # 查询示例
        # results = db.match_nodes("Person", {"age": 30})
        # print(f"Found {len(results)} node(s)")

        # 更新示例
        # updated_node = db.update_node(node1["element_id"], {"age": 31})
        # print(f"Updated age to: {updated_node['properties']['age']}")

        # 复制节点
        new_node = db.copy_node_and_relations(
            node1["element_id"], {"name": "Trudy", "age": "16"}
        )
        print(new_node)

    finally:
        db.close()
