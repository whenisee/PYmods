import nations
from CurrentVehicle import g_currentVehicle
from PYmodsCore import overrideMethod
from collections import defaultdict
from functools import partial
from gui.Scaleform.daapi.view.lobby.customization.customization_carousel import CustomizationCarouselDataProvider, \
    CustomizationSeasonAndTypeFilterData, CustomizationBookmarkVO, comparisonKey
from gui.Scaleform.daapi.view.lobby.customization.shared import TYPE_TO_TAB_IDX, TYPES_ORDER
from gui.Scaleform.locale.VEHICLE_CUSTOMIZATION import VEHICLE_CUSTOMIZATION
from gui.customization.shared import createCustomizationBaseRequestCriteria, C11N_ITEM_TYPE_MAP
from gui.shared.gui_items import GUI_ITEM_TYPE, ItemsCollection
from gui.shared.utils.requesters import REQ_CRITERIA
from helpers import i18n
from items.components.c11n_constants import SeasonType
from items.vehicles import g_cache
from shared_utils import findFirst
from .shared import CSTabs, tabToItem, getItemSeason, CSMode, ITEM_TO_TABS
from .. import g_config


def createBaseRequirements(ctx, season=None):
    season = season or SeasonType.ALL
    if ctx.isBuy:
        return createCustomizationBaseRequestCriteria(
            g_currentVehicle.item, ctx.eventsCache.questsProgress, ctx.getAppliedItems(), season)
    return REQ_CRITERIA.CUSTOM(lambda item: getItemSeason(item) & season)


@overrideMethod(CustomizationCarouselDataProvider, '__init__')
def init(base, self, *a, **kw):
    base(self, *a, **kw)
    updateTabGroups(self)


def updateTabGroups(self):
    self._allSeasonAndTabFilterData = {}
    visibleTabs = defaultdict(set)
    stylesTabEnabled = {s: False for s in SeasonType.COMMON_SEASONS}
    anchorsData = self._proxy.hangarSpace.getSlotPositions()
    requirement = createBaseRequirements(self._proxy)
    allItems = getItems(GUI_ITEM_TYPE.CUSTOMIZATIONS, self._proxy, requirement)
    for tabIndex in self._proxy.tabsData.ALL:
        self._allSeasonAndTabFilterData[tabIndex] = {}
        for season in SeasonType.COMMON_SEASONS:
            self._allSeasonAndTabFilterData[tabIndex][season] = CustomizationSeasonAndTypeFilterData()

    isBuy = self._proxy.isBuy
    for item in sorted(allItems.itervalues(), key=comparisonKey if isBuy else CSComparisonKey):
        groupName = item.groupUserName if isBuy else getGroupName(item)
        if isBuy:
            tabIndex = TYPE_TO_TAB_IDX.get(item.itemTypeID, -1)
        else:
            tabIndex = findFirst(partial(isItemSuitableForTab, item), CSTabs.ALL, -1)
        if tabIndex not in self._proxy.tabsData.ALL or (
                isBuy and tabIndex == self._proxy.tabsData.CAMOUFLAGE and
                g_currentVehicle.item.descriptor.type.hasCustomDefaultCamouflage) or (
                self._proxy.mode == CSMode.SETUP and tabIndex not in CSTabs.CAMO):
            continue
        for seasonType in SeasonType.COMMON_SEASONS:
            if (item.season if isBuy else getItemSeason(item)) & seasonType:
                seasonAndTabData = self._allSeasonAndTabFilterData[tabIndex][seasonType]
                if groupName and groupName not in seasonAndTabData.allGroups:
                    seasonAndTabData.allGroups.append(groupName)
                seasonAndTabData.itemCount += 1
                if tabIndex == self._proxy.tabsData.STYLE:
                    stylesTabEnabled[seasonType] = True
                if item.itemTypeID in (GUI_ITEM_TYPE.INSCRIPTION, GUI_ITEM_TYPE.EMBLEM, GUI_ITEM_TYPE.PERSONAL_NUMBER):
                    if not self._CustomizationCarouselDataProvider__hasSlots(anchorsData, item.itemTypeID):
                        continue
                visibleTabs[seasonType].add(tabIndex)

    self._proxy.updateVisibleTabsList(visibleTabs, stylesTabEnabled)
    for tabIndex in self._proxy.tabsData.ALL:
        for seasonType in SeasonType.COMMON_SEASONS:
            seasonAndTabData = self._allSeasonAndTabFilterData[tabIndex][seasonType]
            seasonAndTabData.allGroups.append(i18n.makeString(VEHICLE_CUSTOMIZATION.CUSTOMIZATION_FILTER_ALLGROUPS))
            seasonAndTabData.selectedGroupIndex = len(seasonAndTabData.allGroups) - 1


@overrideMethod(CustomizationCarouselDataProvider, '_buildCustomizationItems')
def _buildCustomizationItems(_, self):
    # updateTabGroups(self)
    season = self._seasonID
    isBuy = self._proxy.isBuy
    requirement = createBaseRequirements(self._proxy, season)
    if not isBuy:
        requirement |= REQ_CRITERIA.CUSTOM(partial(isItemSuitableForTab, tabIndex=self._tabIndex))
    seasonAndTabData = self._allSeasonAndTabFilterData[self._tabIndex][season]
    allItemsGroup = len(seasonAndTabData.allGroups) - 1
    if seasonAndTabData.selectedGroupIndex != allItemsGroup:
        selectedGroup = seasonAndTabData.allGroups[seasonAndTabData.selectedGroupIndex]
        requirement |= REQ_CRITERIA.CUSTOMIZATION.ONLY_IN_GROUP(selectedGroup)
    if self._historicOnlyItems:
        criteria = REQ_CRITERIA.CUSTOMIZATION.HISTORICAL
        if isBuy:
            criteria = ~criteria
        requirement |= criteria
    if self._onlyOwnedAndFreeItems:
        requirement |= REQ_CRITERIA.CUSTOM(lambda x: self._proxy.getItemInventoryCount(x) > 0)
    if self._onlyAppliedItems:
        appliedItems = self._proxy.getAppliedItems(isOriginal=False)
        requirement |= REQ_CRITERIA.CUSTOM(lambda x: x.intCD in appliedItems)
    allItems = getItems(tabToItem(self._tabIndex, self._proxy.isBuy), self._proxy, requirement)
    self._customizationItems = []
    self._customizationBookmarks = []
    lastGroup = None
    for idx, item in enumerate(sorted(allItems.itervalues(), key=comparisonKey if isBuy else CSComparisonKey)):
        groupName = getGroupName(item)
        groupID = item.groupID
        group = groupID if isBuy else groupName
        if item.intCD == self._selectIntCD:
            self._selectedIdx = self.itemCount
            self._selectIntCD = None
        if group != lastGroup:
            lastGroup = group
            self._customizationBookmarks.append(
                CustomizationBookmarkVO((item.groupUserName if isBuy else groupName), idx).asDict())
        self._customizationItems.append(item.intCD)
        self._itemSizeData.append(item.isWide())

    self._proxy.setCarouselItems(self.collection)


def isItemSuitableForTab(item, tabIndex):
    if item is None or tabIndex not in ITEM_TO_TABS[item.itemTypeID]:
        return False
    if tabIndex in (CSTabs.EMBLEM, CSTabs.INSCRIPTION):
        return True
    vehicle = g_currentVehicle.item
    if tabIndex in (CSTabs.STYLE, CSTabs.PAINT, CSTabs.EFFECT):
        return mayInstall(item, vehicle)
    isGlobal = g_config.isCamoGlobal(item.descriptor)
    return not (
            (tabIndex == CSTabs.CAMO_SHOP and (item.isHidden or item.priceGroup == 'custom')) or
            (tabIndex == CSTabs.CAMO_HIDDEN and (not item.isHidden or isGlobal or item.priceGroup == 'custom')) or
            (tabIndex == CSTabs.CAMO_GLOBAL and not isGlobal) or
            (tabIndex == CSTabs.CAMO_CUSTOM and item.priceGroup != 'custom'))


def mayInstall(self, vehicle):
    return True if not self.descriptor.filter else matchVehicleType(self.descriptor.filter, vehicle.descriptor.type)


def matchVehicleType(self, vehicleType):
    include = not self.include or any((matchVehicleLevel(f, vehicleType) for f in self.include))
    return include and not (self.exclude and any((matchVehicleLevel(f, vehicleType) for f in self.exclude)))


def matchVehicleLevel(self, vehicleType):
    return not self.levels or vehicleType.level in self.levels


def CSComparisonKey(item):
    return TYPES_ORDER.index(item.itemTypeID), getGroupName(item), item.id


def getGroupName(item):
    groupName = item.groupUserName
    nationIDs = []
    if item.descriptor.filter:
        for filterNode in item.descriptor.filter.include:
            if filterNode.nations:
                nationIDs += filterNode.nations
    if len(nationIDs) == 1:
        nationUserName = i18n.makeString('#vehicle_customization:repaint/%s_base_color' % nations.NAMES[nationIDs[0]])
    elif len(nationIDs) > 1:
        nationUserName = g_config.i18n['UI_flashCol_camoGroup_multinational']
    else:
        nationUserName = g_config.i18n['UI_flashCol_camoGroup_special']
    if not groupName:
        groupName = g_config.i18n['UI_flashCol_camoGroup_special']
    else:  # HangarPainter support
        nationUserName = nationUserName.replace('</font>', '')
        if ' ' in nationUserName.replace('<font ', ''):
            nationUserName = nationUserName.rsplit(' ', 1)[0]
        if '>' in groupName:
            groupName = groupName.split('>', 1)[1]
        groupName = nationUserName + ' / ' + groupName
    return groupName


def getItems(itemTypeID, ctx, criteria):
    if not isinstance(itemTypeID, tuple):
        itemTypeID = (itemTypeID,)
    if ctx.isBuy:
        return ctx.itemsCache.items.getItems(itemTypeID, criteria)
    else:
        result = ItemsCollection()
        itemGetter = ctx.itemsCache.items.getItemByCD
        itemTypes = g_cache.customization20().itemTypes
        for typeID in itemTypeID:
            for item in itemTypes[C11N_ITEM_TYPE_MAP[typeID]].itervalues():
                guiItem = itemGetter(item.compactDescr)
                if criteria(guiItem):
                    result[guiItem.intCD] = guiItem
        return result
