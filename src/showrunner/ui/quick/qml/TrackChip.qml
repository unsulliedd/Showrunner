import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// One track signature of a batch on Overview: a click on its header keeps or drops the track in every file (adds a
// paired file), the star and F set the flags, and the ▾ (the header's last control) folds the chip open to list each
// file's name for the track, then the files that lack it. `chip` is a header from the controller; `namesOpen`, `rows`
// and `missing` say whether the place has it open and what it lists. An open chip grows inside its own frame: wider,
// when its names need it, up to the width its parent gives it, and taller up to `names_height`, where the list scrolls.
// Where the tracks carry several names, each name is a line of its own that a click keeps or drops (a rule by name
// ahead of the chip's choice); the list is one tab stop, Up and Down move along it and Space or Return acts.
Item {
    id: control

    required property var chip
    property bool namesOpen: false
    property var rows: []
    property string missing: ""
    // Why the plan keeps the track in some files though it is dropped; shown above the names, where it is seen first.
    property string held: ""
    readonly property bool dropped: chip.state === "dropped"
    readonly property bool paired: chip.paired
    readonly property bool clickable: rows.some(row => row.clickable)
    // Room the list's text needs, from the longest line (the names are set in a fixed-width face).
    readonly property real listWidth: metrics.advanceWidth + 2 * Theme.space_md + Theme.scroll_thumb + 2 * Theme.space_sm

    signal namesToggled

    objectName: "chip" + chip.id
    implicitWidth: namesOpen ? Math.max(header.implicitWidth, listWidth) : header.implicitWidth
    implicitHeight: header.height + (namesOpen ? foldout.height + Theme.space_md : 0)

    TextMetrics {
        id: metrics

        font.family: Theme.mono
        font.pixelSize: Theme.text_sm
        text: control.namesOpen ? control.rows.reduce((a, b) => b.text.length > a.length ? b.text : a, "") : ""
    }

    Rectangle {
        anchors.fill: parent
        visible: !control.paired
        radius: Theme.radius_md
        color: control.dropped ? Theme.drop_soft : Theme.panel
        border.width: Theme.stroke
        border.color: header.visualFocus ? Theme.control : control.dropped ? Theme.drop : Theme.line_strong
    }

    DashedFrame {
        anchors.fill: parent
        visible: control.paired
        radius: Theme.radius_md
        stroke: header.visualFocus ? Theme.control : control.chip.state === "added" ? Theme.add : Theme.line_strong
    }

    // The chip's frame takes a click that lands on it outside the header, so none reaches what lies behind.
    MouseArea {
        anchors.fill: parent
    }

    AbstractButton {
        id: header

        objectName: "chipHeader"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        implicitHeight: Theme.row_lg
        // The same room on both sides, so no badge, flag or arrow touches the chip's edge.
        leftPadding: Theme.space_md
        rightPadding: Theme.space_md
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        Accessible.role: Accessible.Button
        Accessible.name: [control.chip.code, control.chip.title, control.chip.name, control.chip.button,
                          control.chip.from || control.chip.over || ""].join(" ")
        onClicked: app.toggle_keep(control.chip.id)

        background: Rectangle {
            radius: Theme.radius_md
            color: header.hovered && !control.dropped ? Theme.panel_3 : "transparent"
        }

        contentItem: RowLayout {
            spacing: Theme.space_md

            Icon {
                visible: control.paired
                name: "plus"
                size: Theme.icon_sm
                color: control.chip.state === "added" ? Theme.add : Theme.faint
            }

            CodeBadge {
                code: control.chip.code
                look: control.chip.state
            }

            UiText {
                // The title, the name and the count give way together (each cut short in proportion to its length)
                // when the chip is wider than its row, so the flags and the arrow keep their place. The name has no
                // least width, the count and the title have one, so the name goes first.
                Layout.fillWidth: true
                Layout.maximumWidth: implicitWidth
                Layout.minimumWidth: Math.min(implicitWidth, Theme.chip_title_min_width)
                text: control.chip.title
                color: control.dropped ? Theme.drop : Theme.ink
                font.strikeout: control.dropped
                font.weight: Font.Medium
            }

            UiText {
                Layout.fillWidth: true
                Layout.maximumWidth: Math.min(implicitWidth, Theme.chip_name_width)
                visible: control.chip.name !== ""
                text: control.chip.name
                color: control.dropped ? Theme.drop : Theme.muted
                font.strikeout: control.dropped
                font.pixelSize: Theme.text_sm
            }

            UiText {
                Layout.fillWidth: true
                Layout.maximumWidth: implicitWidth
                Layout.minimumWidth: Math.min(implicitWidth, Theme.chip_count_min_width)
                visible: control.chip.count !== ""
                text: control.chip.count
                color: Theme.change
                font.pixelSize: Theme.text_sm
            }

            PlaceMark {
                objectName: "placeMark"
                Layout.maximumWidth: implicitWidth
                choice: control.chip
            }

            FlagButton {
                objectName: "defaultFlag"
                visible: !control.dropped && control.chip.flags
                flag: "default"
                on: control.chip.default
                onClicked: app.toggle_flag(control.chip.id, "default")
            }

            FlagButton {
                visible: !control.dropped && control.chip.flags && control.chip.kind === "subtitle"
                flag: "forced"
                on: control.chip.forced
                onClicked: app.toggle_flag(control.chip.id, "forced")
            }

            // Where a chip widened for its names keeps its arrow at the end, as a chip at its own width has it.
            Item {
                Layout.fillWidth: true
                Layout.preferredWidth: 0
                visible: control.namesOpen
            }

            IconButton {
                objectName: "namesButton"
                visible: control.chip.names
                implicitWidth: Theme.row_sm
                implicitHeight: Theme.row_sm
                iconName: "down"
                // The arrow turns up while its list is open.
                rotation: control.namesOpen ? 180 : 0
                label: Strings.t(control.namesOpen ? "tracks.names.close" : "tracks.names.open")
                active: control.namesOpen
                onClicked: control.namesToggled()
            }
        }
    }

    Item {
        id: foldout

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.leftMargin: Theme.space_md
        anchors.rightMargin: Theme.space_md
        visible: control.namesOpen
        height: Math.min(list.contentHeight, Theme.names_height)

        ListView {
            id: list

            objectName: "chipNameRows"
            anchors.fill: parent
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            // A count, not the lines: a new plan of the same batch then updates the delegates in place.
            model: control.namesOpen ? control.rows.length : 0
            ScrollBar.vertical: Scroller {}
            Accessible.role: Accessible.List
            activeFocusOnTab: control.clickable
            Keys.onSpacePressed: toggleCurrent()
            Keys.onReturnPressed: toggleCurrent()
            Keys.onEnterPressed: toggleCurrent()

            function toggleCurrent() {
                const row = control.rows[currentIndex]
                if (row && row.clickable)
                    app.toggle_name(control.chip.id, row.name)
            }

            // The wheel over a list that scrolls moves only the list, also at its ends; the tracks box behind it
            // scrolls with the wheel anywhere else, and over a list that fits.
            WheelHandler {
                enabled: list.contentHeight > list.height
                onWheel: event => {
                    const step = event.pixelDelta.y !== 0 ? event.pixelDelta.y : event.angleDelta.y / 2
                    list.contentY = Math.max(0, Math.min(list.contentHeight - list.height, list.contentY - step))
                }
            }
            Accessible.name: Strings.t("tracks.names.open")

            delegate: Item {
                id: line

                required property int index
                readonly property var row: control.rows[index] ?? ({"text": "", "name": "", "clickable": false, "dropped": false, "from": "", "over": "", "short": "", "label": ""})
                readonly property bool current: ListView.isCurrentItem && list.activeFocus && row.clickable

                objectName: "chipNameRow"
                width: list.width - Theme.scroll_thumb - Theme.space_sm
                height: Theme.row_sm
                Accessible.role: row.clickable ? Accessible.Button : Accessible.StaticText
                Accessible.name: row.label

                Rectangle {
                    anchors.fill: parent
                    visible: row.clickable && (hover.hovered || line.current)
                    radius: Theme.radius_sm
                    color: hover.hovered ? Theme.panel_3 : "transparent"
                    border.width: line.current ? Theme.stroke : 0
                    border.color: Theme.control
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.space_sm
                    anchors.rightMargin: Theme.space_sm
                    spacing: Theme.space_md

                    UiText {
                        Layout.fillWidth: true
                        text: line.row.text
                        mono: true
                        color: line.row.dropped ? Theme.drop : Theme.ink
                        font.strikeout: line.row.dropped
                    }

                    PlaceMark {
                        objectName: "nameMark"
                        choice: line.row
                    }
                }

                HoverHandler {
                    id: hover

                    enabled: line.row.clickable
                    cursorShape: Qt.PointingHandCursor
                }

                TapHandler {
                    enabled: line.row.clickable
                    onTapped: {
                        list.currentIndex = line.index
                        app.toggle_name(control.chip.id, line.row.name)
                    }
                }
            }

            header: Item {
                width: list.width - Theme.scroll_thumb - Theme.space_sm
                // Sized by binding, not by a layout, so the list starts below nothing when the reason is the first thing.
                readonly property real hintHeight: control.clickable ? hint.height + Theme.space_sm : 0
                height: hintHeight + (control.held !== "" ? reason.implicitHeight + Theme.space_sm : 0)

                Row {
                    id: hint

                    visible: control.clickable
                    spacing: Theme.space_md

                    UiText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: Strings.t("tracks.names.hint")
                        color: Theme.muted
                        font.pixelSize: Theme.text_sm
                    }

                    HelpTip {
                        anchors.verticalCenter: parent.verticalCenter
                        topic: "names"
                    }
                }

                UiText {
                    id: reason

                    anchors.left: parent.left
                    anchors.right: parent.right
                    y: parent.hintHeight
                    visible: control.held !== ""
                    text: control.held
                    color: Theme.change
                    font.pixelSize: Theme.text_sm
                    wrapMode: Text.WordWrap
                }
            }

            footer: Item {
                width: list.width - Theme.scroll_thumb - Theme.space_sm
                height: control.missing !== "" ? note.implicitHeight + Theme.space_sm : 0

                UiText {
                    id: note

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    visible: control.missing !== ""
                    text: control.missing
                    color: Theme.change
                    font.pixelSize: Theme.text_sm
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
}
