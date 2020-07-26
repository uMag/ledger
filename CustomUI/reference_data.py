import logging
from datetime import datetime

from PySide2.QtCore import Qt, Signal, Property, Slot, QEvent
from PySide2.QtSql import QSqlQuery, QSqlRelationalDelegate
from PySide2.QtWidgets import QDialog
from PySide2.QtWidgets import QStyledItemDelegate

from UI.ui_reference_data_dlg import Ui_ReferenceDataDialog
from CustomUI.helpers import UseSqlTable, ConfigureTableView, hcol_idx, rel


# --------------------------------------------------------------------------------------------------------------
# Class to display and edit table with reference data (accounts, categories, tags...)
# --------------------------------------------------------------------------------------------------------------
class ReferenceDataDialog(QDialog, Ui_ReferenceDataDialog):
    # ----------------------------------------------------------------------------------------------------------
    # Params:
    # db - QSqlDatabase object for DB operations
    # table - name of the table to display/edit
    # columns - list of tuples - see helpers.py for details
    # title - title of dialog window
    # search_field - field name which will be used for search from GUI
    # tree_view - table will be displayed as hierarchical tree with help of 3 columns: 'id', 'pid' and 'children_count'
    #  ('pid' will identify parent row for current row, and '+' will be displayed for row with 'children_count'>0
    # relations - list of tuples that define lookup relations to other tables in database:
    def __init__(self, db, table, columns, title='',
                 search_field=None, toggle=None, tree_view=False, relations=None):
        QDialog.__init__(self)
        self.setupUi(self)

        self.selected_id = 0
        self.p_selected_name = ''
        self.tree_view = tree_view
        self.parent = 0
        self.last_parent = 0
        self.group_id = None
        self.group_key_field = None
        self.group_fkey_field = None
        self.toggle_state = False
        self.toggle_field = None
        self.search_text = ""
        self.search_field = search_field

        self.db = db
        self.table = table
        self.Model = UseSqlTable(self.db, self.table, columns, relations)
        ConfigureTableView(self.DataView, self.Model, columns)

        # Storage of delegates inside class is required to keep ownership and prevent SIGSEGV as
        # https://doc.qt.io/qt-5/qabstractitemview.html#setItemDelegateForColumn says:
        # Any existing column delegate for column will be removed, but not deleted.
        # QAbstractItemView does not take ownership of delegate.
        self.delegates = []
        for column in columns:
            if column[hcol_idx.DELEGATE] is not None:
                self.delegates.append(column[hcol_idx.DELEGATE](self.DataView))
                self.DataView.setItemDelegateForColumn(self.Model.fieldIndex(column[hcol_idx.DB_NAME]),
                                                       self.delegates[-1])

        self.GroupLbl.setVisible(False)
        self.GroupCombo.setVisible(False)
        if relations is not None:
            for relation in relations:
                if relation[rel.GROUP_NAME] is not None:
                    self.GroupLbl.setVisible(True)
                    self.GroupLbl.setText(relation[rel.GROUP_NAME])
                    self.GroupCombo.setVisible(True)
                    self.group_key_field = relation[rel.KEY_FIELD]
                    self.group_fkey_field = relation[rel.FOREIGN_KEY]
                    relation_model = self.Model.relationModel(self.Model.fieldIndex(relation[rel.KEY_FIELD]))
                    self.GroupCombo.setModel(relation_model)
                    self.GroupCombo.setModelColumn(relation_model.fieldIndex(relation[rel.LOOKUP_FIELD]))

        self.Toggle.setVisible(False)
        if toggle:
            self.Toggle.setVisible(True)
            self.toggle_field = toggle[0]
            self.Toggle.setText(toggle[1])

        self.setWindowTitle(title)
        if self.search_field is not None:
            self.SearchFrame.setVisible(True)
        else:
            self.SearchFrame.setVisible(False)
        self.UpBtn.setVisible(self.tree_view)

        self.SearchString.textChanged.connect(self.OnSearchChange)
        self.UpBtn.clicked.connect(self.OnUpClick)
        self.GroupCombo.currentIndexChanged.connect(self.OnGroupChange)
        self.Toggle.stateChanged.connect(self.OnToggleChange)
        self.AddBtn.clicked.connect(self.OnAdd)
        self.RemoveBtn.clicked.connect(self.OnRemove)
        self.CommitBtn.clicked.connect(self.OnCommit)
        self.RevertBtn.clicked.connect(self.OnRevert)
        self.DataView.clicked.connect(self.OnClicked)
        self.DataView.selectionModel().selectionChanged.connect(self.OnRowSelected)
        self.Model.dataChanged.connect(self.OnDataChanged)

        self.Model.select()
        self.setFilter()

    def getSelectedName(self):
        if self.selected_id == 0:
            return "ANY"
        else:
            return self.p_selected_name

    def setSelectedName(self, selected_id):
        pass

    @Signal
    def selected_name_changed(self):
        pass

    SelectedName = Property(str, getSelectedName, setSelectedName, notify=selected_name_changed)

    @Slot()
    def OnDataChanged(self):
        self.CommitBtn.setEnabled(True)
        self.RevertBtn.setEnabled(True)

    @Slot()
    def OnAdd(self):
        new_record = self.Model.record()
        if self.tree_view:
            new_record.setValue("pid", self.parent)  # set current parent
        assert self.Model.insertRows(0, 1)
        self.Model.setRecord(0, new_record)
        self.CommitBtn.setEnabled(True)
        self.RevertBtn.setEnabled(True)

    @Slot()
    def OnRemove(self):
        idx = self.DataView.selectionModel().selection().indexes()
        selected_row = idx[0].row()
        assert self.Model.removeRow(selected_row)
        self.CommitBtn.setEnabled(True)
        self.RevertBtn.setEnabled(True)

    @Slot()
    def OnCommit(self):
        if not self.Model.submitAll():
            logging.fatal(self.tr("Action submit failed: ") + self.Model.lastError().text())
            return
        self.CommitBtn.setEnabled(False)
        self.RevertBtn.setEnabled(False)

    @Slot()
    def OnRevert(self):
        self.Model.revertAll()
        self.CommitBtn.setEnabled(False)
        self.RevertBtn.setEnabled(False)

    def setFilter(self):  # TODO: correctly combine different conditions
        conditions = []
        if self.search_text:
            conditions.append(f"{self.search_field} LIKE '%{self.search_text}%'")
        else:
            if self.tree_view:
                conditions.append(f"pid={self.parent}")

        if self.group_id:
            conditions.append(f"{self.table}.{self.group_key_field}={self.group_id}")

        if self.toggle_field:
            if not self.toggle_state:
                conditions.append(f"{self.table}.{self.toggle_field}=1")

        condition = ""
        for line in conditions:
            condition += line + " AND "
        condition = condition[:-len(" AND ")]

        self.DataView.model().setFilter(condition)

    @Slot()
    def OnSearchChange(self):
        self.search_text = self.SearchString.text()
        self.setFilter()

    @Slot()
    def OnRowSelected(self, selected, _deselected):
        idx = selected.indexes()
        if idx:
            selected_row = idx[0].row()
            self.selected_id = self.DataView.model().record(selected_row).value("id")
            self.p_selected_name = self.DataView.model().record(selected_row).value("name")

    @Slot()
    def OnClicked(self, index):
        if index.column() == 0:
            selected_row = index.row()
            self.parent = self.DataView.model().record(selected_row).value("id")
            self.last_parent = self.DataView.model().record(selected_row).value("pid")
            if self.search_text:
                self.SearchString.setText("")  # it will also call self.setFilter()
            else:
                self.setFilter()

    @Slot()
    def OnUpClick(self):
        if self.search_text:  # list filtered by search string
            return
        query = QSqlQuery(self.db)
        query.prepare(f"SELECT c2.pid FROM {self.table} AS c1 LEFT JOIN {self.table} AS c2 ON c1.pid=c2.id "
                      f"WHERE c1.id = :current_id")
        current_id = self.DataView.model().record(0).value("id")
        if current_id is None:
            pid = self.last_parent
        else:
            query.bindValue(":current_id", current_id)
            query.exec_()
            query.next()
            pid = query.value(0)
            if pid == '':
                pid = 0
        self.parent = pid
        self.setFilter()

    @Slot()
    def OnGroupChange(self, list_id):
        model = self.GroupCombo.model()
        self.group_id = model.data(model.index(list_id, model.fieldIndex(self.group_fkey_field)))
        self.setFilter()

    @Slot()
    def OnToggleChange(self, state):
        if state == 0:
            self.toggle_state = False
        else:
            self.toggle_state = True
        self.setFilter()

# ===================================================================================================================
# Delegates to customize view of columns
# ===================================================================================================================

# -------------------------------------------------------------------------------------------------------------------
# Display '+' if element have children
class ReferenceTreeDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        QStyledItemDelegate.__init__(self, parent)

    def paint(self, painter, option, index):
        painter.save()
        model = index.model()
        children_count = model.data(model.index(index.row(), model.fieldIndex("children_count")), Qt.DisplayRole)
        text = ""
        if children_count:
            text = "+"
        painter.drawText(option.rect, Qt.AlignHCenter, text)
        painter.restore()

# -------------------------------------------------------------------------------------------------------------------
# Display '*' if true and empty cell if false
# Toggle True/False by mouse click
class ReferenceBoolDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        QStyledItemDelegate.__init__(self, parent)

    def paint(self, painter, option, index):
        painter.save()
        model = index.model()
        status = model.data(index, Qt.DisplayRole)
        if status:
            text = " * "
        else:
            text = ""
        painter.drawText(option.rect, Qt.AlignHCenter, text)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonPress:
            if model.data(index, Qt.DisplayRole):  # Toggle value - from 1 to 0 and from 0 to 1
                model.setData(index, 0)
            else:
                model.setData(index, 1)
        return True

# -------------------------------------------------------------------------------------------------------------------
# Make integer alignment to the right
class ReferenceIntDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        QStyledItemDelegate.__init__(self, parent)

    def paint(self, painter, option, index):
        painter.save()
        model = index.model()
        value = model.data(index, Qt.DisplayRole)
        painter.drawText(option.rect, Qt.AlignRight, f"{value} ")
        painter.restore()

# -------------------------------------------------------------------------------------------------------------------
# Format unix timestamp into readable form '%d/%m/%Y %H:%M:%S'
class ReferenceTimestampDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        QStyledItemDelegate.__init__(self, parent)

    def paint(self, painter, option, index):
        painter.save()
        model = index.model()
        timestamp = model.data(index, Qt.DisplayRole)
        if timestamp:
            text = datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M:%S')
        else:
            text = ""
        painter.drawText(option.rect, Qt.AlignLeft, text)
        painter.restore()

# -------------------------------------------------------------------------------------------------------------------
# The class itself is empty but it activates built-in editors for lookup tables
class ReferenceLookupDelegate(QSqlRelationalDelegate):
    def __init__(self, parent=None):
        QSqlRelationalDelegate.__init__(self, parent)
