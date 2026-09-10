"""MVP용 메모리 저장소. 이후 DB 저장소로 교체할 수 있습니다."""

from blog_importer.models import BlogPost

from .models import BrainRecord, RawContent, build_metadata


class BrainRepository:
    def __init__(self) -> None:
        self._records: dict[str, BrainRecord] = {}
        self._source_urls: set[str] = set()

    def add(self, post: BlogPost) -> bool:
        if post.content_hash in self._records or post.source_url in self._source_urls:
            return False
        self._records[post.content_hash] = BrainRecord(RawContent.from_post(post), build_metadata(post))
        self._source_urls.add(post.source_url)
        return True

    def add_many(self, posts: list[BlogPost]) -> int:
        return sum(self.add(post) for post in posts)

    def all(self) -> tuple[BrainRecord, ...]:
        return tuple(self._records.values())

    def get_by_hash(self, content_hash: str) -> BrainRecord | None:
        return self._records.get(content_hash)