"""gainge_crawler 단위테스트 — GraphQL 응답 → PostRef/RawPost 매핑, body 합본, 증분 필터.

실네트워크 없이 FakeGaingeClient(graphql 응답 고정)로 list_post_refs/crawl_post 계약을 고정한다.
"""

from __future__ import annotations

from datetime import datetime

from app.ingest.gainge_crawler import _parse_published, crawl_post, list_post_refs


class _Settings:
    gainge_base = "https://cudo.gainge.com"


class FakeGaingeClient:
    """graphql() 만 흉내내는 목 — operationName 으로 카테고리/Posts 응답을 분기."""

    def __init__(self, categories: list[dict], posts_by_cat: dict[int, list[dict]]) -> None:
        self._settings = _Settings()
        self._cache: dict[int, dict] = {}
        self._categories = categories
        self._posts = posts_by_cat

    def graphql(self, operation_name, query, variables=None):
        if operation_name == "Get_all_category_groups":
            return {"get_all_category_groups": {"categoryGroups": self._categories}}
        if operation_name == "Posts":
            cseq = variables["input"]["categorySeq"]
            items = self._posts.get(cseq, [])
            return {"get_all_posts": {"posts": {"totalPages": 1, "postsByUser": items}}}
        raise AssertionError(f"unexpected op {operation_name}")


def _post(seq: int, **over):
    base = {
        "seq": seq, "title": f"영상{seq}", "description": "설명문",
        "content": "<p>본문 HTML</p>", "uploader": "한종철",
        "published_at": "2024-03-05T06:38:08.000Z", "view_cnt": 126,
        "is_video": True, "postCategoryGroupName": "솔루션_ 지식공유",
        "postCategoryName": "솔루_개발자 교육",
        "clip": {"ott_hls_path": "/vod/x.m3u8", "register_value": "/files/x.mp4"},
    }
    base.update(over)
    return base


def _client():
    cats = [{"name": "솔루션", "categories": [{"seq": 6567, "name": "개발자", "is_using": True}]}]
    return FakeGaingeClient(cats, {6567: [_post(56517), _post(56518)]})


def test_list_post_refs_maps_and_caches():
    client = _client()
    refs = list_post_refs(client, 800000000, None, None)
    assert {r.art_no for r in refs} == {56517, 56518}
    ref = next(r for r in refs if r.art_no == 56517)
    assert ref.title == "영상56517"
    assert ref.author == "한종철"
    assert ref.view_count == 126
    assert ref.posted_at == datetime.fromisoformat("2024-03-05T06:38:08+00:00")
    # crawl_post 가 소비할 캐시에 게시글 dict 가 적재됨.
    assert client._cache[56517]["title"] == "영상56517"


def test_list_post_refs_collects_all_ignoring_watermark():
    client = _client()
    # gainge 는 워터마크 미사용 — since_art_no 를 줘도 전체 수집(cross-run 누락 방지 + upsert 멱등).
    refs = list_post_refs(client, 800000000, 56517, None)
    assert {r.art_no for r in refs} == {56517, 56518}
    assert set(client._cache) == {56517, 56518}


def test_crawl_post_composes_body_and_absolute_url():
    client = _client()
    refs = list_post_refs(client, 800000000, None, None)
    ref = next(r for r in refs if r.art_no == 56517)
    raw = crawl_post(client, 800000000, ref)

    assert raw.art_no == 56517
    assert raw.source_url == "https://cudo.gainge.com/post/56517"  # 절대 URL.
    assert raw.attachments == ()  # 영상은 첨부 없음.
    # body 에 카테고리·설명·content·영상링크·HLS 가 합본.
    assert "[카테고리] 솔루션_ 지식공유 > 솔루_개발자 교육" in raw.body_html
    assert "설명문" in raw.body_html
    assert "본문 HTML" in raw.body_html
    assert "영상 보기: https://cudo.gainge.com/post/56517" in raw.body_html
    assert "스트리밍(HLS): https://cudo.gainge.com/vod/x.m3u8" in raw.body_html
    # 리뷰 ③: load-bearing URL 은 content HTML 보다 앞(malformed content 흡수 방지).
    assert raw.body_html.index("영상 보기:") < raw.body_html.index("본문 HTML")


def test_parse_published_handles_z_and_none():
    assert _parse_published("2024-03-05T06:38:08.000Z") == datetime.fromisoformat(
        "2024-03-05T06:38:08+00:00"
    )
    assert _parse_published(None) is None
    assert _parse_published("garbage") is None


def test_category_skips_unused():
    cats = [{"name": "g", "categories": [
        {"seq": 1, "name": "a", "is_using": True},
        {"seq": 2, "name": "b", "is_using": False},
    ]}]
    client = FakeGaingeClient(cats, {1: [_post(10)], 2: [_post(20)]})
    refs = list_post_refs(client, 800000000, None, None)
    assert [r.art_no for r in refs] == [10]  # is_using=False 카테고리(2)는 미수집.


def test_posts_forbidden_category_isolated():
    # 일부 카테고리가 403(FORBIDDEN→RuntimeError)이어도 접근 가능한 카테고리는 정상 수집(보드 미중단).
    cats = [{"name": "g", "categories": [
        {"seq": 1, "name": "a", "is_using": True},
        {"seq": 2, "name": "b", "is_using": True},
    ]}]
    client = FakeGaingeClient(cats, {1: [_post(10)], 2: [_post(20)]})
    orig = client.graphql

    def gql(op, query, variables=None):
        if op == "Posts" and variables["input"]["categorySeq"] == 2:
            raise RuntimeError("gainge GraphQL 오류(Posts): FORBIDDEN 403")
        return orig(op, query, variables)

    client.graphql = gql
    refs = list_post_refs(client, 800000000, None, None)
    assert [r.art_no for r in refs] == [10]  # 카테고리 2(403)는 격리, 1만 수집.
