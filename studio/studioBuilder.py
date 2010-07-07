# -*- coding: utf-8 -*-

###########################################################################
#    OCRFeeder - The complete OCR suite
#    Copyright (C) 2009 Joaquim Rocha
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
###########################################################################

from util import lib
from util.constants import *
from util.cliutils import ArgsRetriever
import sys
import os.path
import urllib
from studio import widgetPresenter
from studio.widgetModeler import SourceImagesSelector, SourceImagesSelectorIconView, ImageReviewer_Controler
from studio.dataHolder import create_images_dict_from_liststore, DataBox, TextData
from studio.customWidgets import SelectableBoxesArea
from feeder.ocrEngines import Engine, OcrEnginesManager
from configuration import ConfigurationManager
from util.asyncworker import AsyncItem
import gettext
import locale
_ = gettext.gettext

import pygtk
pygtk.require('2.0')
import gtk

class Studio:

    EXPORT_FORMATS = ['HTML', 'ODT']
    TARGET_TYPE_URI_LIST = 80

    def __init__(self):

        # i18n
        languages = []
        lc, encoding = locale.getdefaultlocale()
        if lc:
            languages = [lc]
        languages += DEFAULT_LANGUAGES
        gettext.bindtextdomain(OCRFEEDER_COMPACT_NAME, LOCALE_DIR)
        gettext.textdomain(OCRFEEDER_COMPACT_NAME)
        language = gettext.translation(OCRFEEDER_COMPACT_NAME, LOCALE_DIR,
                                       languages = languages, fallback = True)
        _ = language.gettext
        self.title = OCRFEEDER_STUDIO_NAME
        self.main_window = widgetPresenter.MainWindow()
        self.main_window.setTitle(self.title)
        cli_command_retriever = ArgsRetriever(sys.argv)
        imgs = cli_command_retriever.getParams('--images')
        self.configuration_manager = ConfigurationManager()
        self.ocr_engines_manager = OcrEnginesManager(self.configuration_manager)
        self.ocr_engines_manager.makeEnginesFromFolder(self.configuration_manager.user_engines_folder)
        self.ocr_engines = self.ocr_engines_manager.ocr_engines
        self.configuration_manager.loadConfiguration()
        self.source_images_selector = SourceImagesSelector(imgs)
        self.source_images_selector.connect('selection_changed', self.selectionChanged)
        self.source_images_icon_view = SourceImagesSelectorIconView(self.source_images_selector)
        self.source_images_icon_view.setDeleteCurrentPageFunction(self.deleteCurrentPage)
        self.source_images_icon_view.connect('drag_data_received', self.dragDataReceived)
        self.source_images_icon_view.connect('drag_drop', self.dragDrop)
        self.source_images_icon_view.drag_dest_set(gtk.DEST_DEFAULT_MOTION | gtk.DEST_DEFAULT_HIGHLIGHT,
                                                   [('text/uri-list', 0, self.TARGET_TYPE_URI_LIST)], gtk.gdk.ACTION_COPY)
        self.source_images_icon_view.show()
        self.main_window.main_area_left.add_with_viewport(self.source_images_icon_view)
        self.images_selectable_area = {}
        self.images_dict = create_images_dict_from_liststore(self.source_images_selector.list_store)
        self.source_images_controler = ImageReviewer_Controler(self.main_window,
                                                               self.images_dict,
                                                               self.source_images_icon_view,
                                                               self.ocr_engines,
                                                               self.configuration_manager)
        self.project_name = None

        toolbar_callback_dict = {'detection': self.__recognizeCurrentPageAction,
                         'export_to_odt': self.exportToOdt}

        menubar_callback_dict = {'exit': self.quit, 'add_image': self.addImage, 'export_to_odt': self.exportToOdt, 'edit_page': self.choosePageSize,
                                 'delete_page': self.deleteCurrentPage, 'export_dialog': self.exportDialog, 'add_folder': self.addFolder,
                                 'import_pdf': self.importPdf, 'save_project': self.saveProject, 'save_project_as': self.saveProjectAs,
                                 'open_project': self.openProject, 'append_project': self.appendProject,'clear': self.clear,
                                 'unpaper': self.unpaper, 'preferences': self.preferences, 'about': self.about,
                                 'ocr_engines': self.ocrEngines, 'zoom_in': self.zoomIn, 'zoom_out': self.zoomOut,
                                 'zoom_fit': self.zoomFit, 'reset_zoom': self.resetZoom,
                                 'recognize_areas': self.source_images_controler.recognizeSelectedAreas,
                                 'select_next_area': self.source_images_controler.selectNextArea,
                                 'select_previous_area': self.source_images_controler.selectPreviousArea,
                                 'select_all_areas': self.source_images_controler.selectAllAreas,
                                 'delete_selected_areas': self.source_images_controler.deleteSelectedAreas,
                                 }

        self.main_window.setHeader(menubar_callback_dict, toolbar_callback_dict)
        self.main_window.setDestroyEvent(self.quit)

        dirs = cli_command_retriever.getParams('--dir')
        if dirs:
            self.__addImagesToReviewer(lib.getImagesFromFolder(dirs[0]))

        self.main_window.setHasSelectedBoxes(False)
        self.main_window.setHasContentBoxes(False)
        self.main_window.setHasImages(not self.source_images_selector.isEmpty())

        # Show dialog to choose system-wide OCR engines when no engine was found
        if not self.ocr_engines:
            engines = self.configuration_manager.getEnginesInSystem()
            if engines:
                add_engines_dialog = widgetPresenter.SystemEnginesDialog(engines)
                response = add_engines_dialog.run()
                if response == gtk.RESPONSE_ACCEPT:
                    for engine in add_engines_dialog.getChosenEngines():
                        self.ocr_engines_manager.addNewEngine(engine)
                add_engines_dialog.destroy()

    def run(self):
        gtk.gdk.threads_init()
        gtk.main()

    def dragDataReceived(self, widget, context, x, y, selection, target_type, timestamp):
        if target_type == self.TARGET_TYPE_URI_LIST:
            uris = selection.data.strip('\r\n\x00').split()
            paths = []
            for uri in uris:
                path = ""
                if uri.startswith('file:\\\\\\'): # windows
                    path = uri[8:]
                elif uri.startswith('file://'): # nautilus, rox
                    path = uri[7:]
                elif uri.startswith('file:'): # xffm
                    path = uri[5:]
                path = urllib.url2pathname(path).strip('\r\n\x00')
                if os.path.isfile(path):
                    paths.append(path)
            for path in paths:
                if os.path.splitext(path)[1] == '.pdf':
                    folder = lib.convertPdfToImages(path, self.configuration_manager.getTemporaryDir())
                    self.__addImagesToReviewer(lib.getImagesFromFolder(folder))
                else:
                    try:
                        self.__addImagesToReviewer([path])
                    except:
                        pass

    def dragDrop(self, widget, context, x, y, timestamp):
        target_atom = widget.drag_dest_find_target(context, widget.drag_dest_get_target_list())
        if target_atom != None:
            widget.drag_get_data(context, target_atom, timestamp)
            context.finish(True, False, timestamp)
        return True

    def addImage(self, widget):
        file_open_dialog = widgetPresenter.FileDialog('open', file_filters = [(_('Images'), ['image/*'], [])])
        response = file_open_dialog.run()
        if response == gtk.RESPONSE_OK:
            for file_name in file_open_dialog.get_filenames():
                self.__addImagesToReviewer([file_name])
        file_open_dialog.destroy()

    def importPdf(self, widget):
        file_open_dialog = widgetPresenter.FileDialog('open', file_filters = [(_('PDF'), ['application/pdf'], [])])
        response = file_open_dialog.run()
        files = []
        if response == gtk.RESPONSE_OK:
            files = file_open_dialog.get_filenames()
        file_open_dialog.destroy()
        for file_name in files:
            dialog = widgetPresenter.QueuedEventsProgressDialog(
                                                 self.main_window.window)
            item = AsyncItem(lib.convertPdfToImages,
                             (file_name,
                              self.configuration_manager.getTemporaryDir()),
                             self.__loadPdfFinishedCb,
                             (dialog,))
            info = (_('Loading PDF'), _('Please wait…'))
            dialog.setItemsList([(info, item)])
            dialog.run()

    def __loadPdfFinishedCb(self, dialog, folder, error):
        self.__addImagesToReviewer(lib.getImagesFromFolder(folder))
        dialog.destroy()

    def addFolder(self, widget):
        file_open_dialog = widgetPresenter.FileDialog('select-folder')
        response = file_open_dialog.run()
        if response == gtk.RESPONSE_OK:
            for folder in file_open_dialog.get_filenames():
                self.__addImagesToReviewer(lib.getImagesFromFolder(folder))
        file_open_dialog.destroy()

    def exportToHtml(self, widget = None):
        self.source_images_controler.exportPagesToHtml(self.source_images_selector.getPixbufsSorted())

    def exportToOdt(self, widget = None):
        self.source_images_controler.exportPagesToOdt(self.source_images_selector.getPixbufsSorted())

    def exportDialog(self, widget):
        export_dialog = widgetPresenter.ExportDialog(_('Export pages'), self.EXPORT_FORMATS)
        response = export_dialog.run()
        if response == gtk.RESPONSE_ACCEPT:
            format = export_dialog.getSelectedFormat().capitalize()
            export_dialog.destroy()
            exec('self.exportTo%s()' % format)
            return None
        export_dialog.destroy()
        return None

    def choosePageSize(self, widget):
        self.source_images_controler.choosePageSize()

    def deleteCurrentPage(self, widget):
        delete_dialog = widgetPresenter.QuestionDialog(_('Are you sure you want to delete the current image?'))
        response = delete_dialog.run()
        if response == gtk.RESPONSE_YES:
            self.source_images_controler.deleteCurrentPage()
            self.source_images_icon_view.deleteCurrentSelection()
        delete_dialog.destroy()

    def __addImagesToReviewer(self, images):
        if not images:
            return
        for image in images:
            pixbuf, image, iter = self.source_images_selector.addImage(image)
            self.source_images_controler.addImage(pixbuf, image)
        tree_path = self.source_images_selector.list_store.get_path(iter)
        self.source_images_icon_view.select_path(tree_path)

    def __recognizeCurrentPageAction(self, widget):
        self.source_images_controler.recognizeCurrentPage()

    def setProjectName(self, project_name):
        self.project_name = project_name
        project_title = os.path.splitext(os.path.basename(self.project_name))[0]
        self.main_window.setTitle('%s - %s' % (self.title, project_title))

    def saveProjectAs(self, widget = None):
        file_name = self.source_images_controler.saveProjectAs()
        if file_name:
            self.setProjectName(file_name)
            self.saveProject()

    def saveProject(self, widget = None):
        if self.project_name:
            self.source_images_controler.saveProject(self.project_name)
        else:
            self.saveProjectAs()

    def appendProject(self, widget = None):
        self.__loadProject(False)

    def openProject(self, widget = None):
        self.__loadProject()

    def __loadProject(self, clear_current = True):
        project_title = self.source_images_controler.openProject(clear_current)
        if project_title:
            self.setProjectName(project_title)

    def clear(self, widget = None):
        self.source_images_controler.clear()

    def unpaper(self, widget = None):
        self.source_images_controler.unpaperTool()

    def preferences(self, widget = None):
        preferences_dialog = widgetPresenter.PreferencesDialog(self.configuration_manager, self.ocr_engines_manager.ocr_engines)
        if preferences_dialog.run() == gtk.RESPONSE_ACCEPT:
            preferences_dialog.saveToManager()
            self.source_images_controler.updateFromConfiguration()
        preferences_dialog.destroy()

    def ocrEngines(self, widget = None):
        ocr_dialog = widgetPresenter.OcrManagerDialog(self.ocr_engines_manager)
        ocr_dialog.run()
        ocr_dialog.destroy()

    def enginesTool(self, widget = None):
        pass

    def selectionChanged(self, selector, is_empty):
        self.main_window.setHasImages(not is_empty)

    def about(self, widget = None):
        from gnome import url_show
        gtk.about_dialog_set_url_hook(lambda x,y,z: url_show(y), "")
        about_dialog = widgetPresenter.CustomAboutDialog()
        if about_dialog.run():
            about_dialog.destroy()

    def zoomIn(self, widget = None):
        self.source_images_controler.zoomIn()

    def zoomOut(self, widget = None):
        self.source_images_controler.zoomOut()

    def resetZoom(self, widget = None):
        self.source_images_controler.resetZoom()

    def zoomFit(self, widget = None):
        self.source_images_controler.zoomFit()

    def quit(self, widget = None, data = None):
        if not self.project_name and not self.source_images_selector.isEmpty():
            quit_dialog = widgetPresenter.QuestionDialog('<b>' + _("The project hasn't been saved.") + '</b>', gtk.BUTTONS_NONE)
            quit_dialog.format_secondary_text(_('Do you want to save it before closing?'))
            quit_dialog.add_buttons(_('Close anyway'), gtk.RESPONSE_NO, gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_SAVE_AS, gtk.RESPONSE_YES)
            response = quit_dialog.run()
            quit_dialog.destroy()
            if response == gtk.RESPONSE_YES:
                self.saveProjectAs()
                self.__main_quit()
            elif response == gtk.RESPONSE_NO:
                quit_dialog.destroy()
                self.__main_quit()
            else:
                return True
        else:
            self.__main_quit()
        return False

    def __main_quit(self):
        self.configuration_manager.configurationToXml()
        gtk.main_quit()
