from browser_harness import macos, macos_ax


def node(role, title="", description="", value="", children=()):
    return {"AXRole": role, "AXTitle": title, "AXDescription": description, "AXValue": value, "children": list(children)}


class FakeSession:
    def __init__(self):
        self.pressed = []

    def string(self, element, name):
        return element.get(name, "")

    def elements(self, element, name):
        return element["children"]

    def press(self, element):
        self.pressed.append(element["AXDescription"] or element["AXTitle"])
        return True


TITLES = macos.ALLOW_SHEET_TITLES
LABELS = macos.ALLOW_BUTTON_LABELS


def chrome_sheet(title="リモート デバッグを許可しますか？", heading="リモート デバッグを許可しますか？"):
    return node(
        "AXSheet",
        title=title,
        children=[
            node("AXGroup", children=[node("AXHeading", title=heading, description=heading)]),
            node(
                "AXGroup",
                children=[
                    node("AXButton", title="[設定] でオフにする", description="[設定] でオフにする"),
                    node("AXButton", title="キャンセル", description="キャンセル"),
                    node("AXButton", title="許可する", description="許可する"),
                ],
            ),
        ],
    )


def test_presses_only_the_allow_button_of_the_allow_sheet():
    session = FakeSession()
    sheet = chrome_sheet()

    assert macos_ax._is_allow_sheet(session, sheet, TITLES)
    assert macos_ax._press_allow(session, sheet, LABELS)
    assert session.pressed == ["許可する"]


def test_recognizes_a_sheet_without_a_title_by_its_heading():
    session = FakeSession()

    assert macos_ax._is_allow_sheet(session, chrome_sheet(title=""), TITLES)


def test_ignores_a_sheet_with_another_title_and_heading():
    session = FakeSession()

    assert not macos_ax._is_allow_sheet(session, chrome_sheet(title="", heading="ページを離れますか？"), TITLES)


def test_reads_the_button_title_when_the_description_is_empty():
    session = FakeSession()
    sheet = node("AXSheet", title="Allow remote debugging?", children=[node("AXButton", title="Allow")])

    assert macos_ax._press_allow(session, sheet, LABELS)
    assert session.pressed == ["Allow"]


def test_presses_nothing_without_an_exact_label():
    session = FakeSession()
    sheet = node("AXSheet", children=[node("AXButton", title="Allow once"), node("AXButton", title="Cancel")])

    assert not macos_ax._press_allow(session, sheet, LABELS)
    assert session.pressed == []
