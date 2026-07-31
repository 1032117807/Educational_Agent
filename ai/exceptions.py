class AIError(Exception):
    """AI 子系统基础异常。"""


class AIConfigurationError(AIError):
    """AI 配置缺失或无效。"""


class AIProviderError(AIError):
    """模型服务调用失败。"""


class DocumentParseError(AIError):
    """文档无法解析。"""


class UnsupportedDocumentTypeError(DocumentParseError):
    """文档类型不在解析器支持范围内。"""


class EmptyDocumentError(DocumentParseError):
    """文档中没有可供处理的文本内容。"""


class RetrievalError(AIError):
    """资料检索失败。"""


class InsufficientEvidenceError(AIError):
    """检索证据不足，不能可靠回答。"""


class CitationValidationError(AIError):
    """模型返回了无效、伪造或不一致的引用。"""