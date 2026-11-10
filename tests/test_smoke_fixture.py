from .conftest import TEST_EMAIL


def test_signed_in_client_lists_no_files(signed_in, fake):
    resp = signed_in.get("/api/files")
    assert resp.status_code == 200
    assert resp.get_json() == {"files": []}


def test_listing_shows_only_own_objects(signed_in, fake):
    fake.put_object(fake.user_id(TEST_EMAIL), "a.txt", b"hi")
    fake.put_object("other-user", "b.txt", b"no")
    names = [f["name"] for f in signed_in.get("/api/files").get_json()["files"]]
    assert names == ["a.txt"]
