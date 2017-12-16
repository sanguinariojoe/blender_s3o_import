#!BPY
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

bl_info = {
    "name": "Import Spring S3O (.s3o)",
    "author": "Jez Kabanov and Jose Luis Cercos-Pita <jlcercos@gmail.com>",
    "version": (0, 6, 0),
    "blender": (2, 7, 4),
    "location": "File > Import > Spring S3O (.s3o)",
    "description": "Import a file in the Spring S3O format",
    "warning": "",
    "wiki_url": "https://springrts.com/wiki/Assimp",
    "tracker_url": "http://springrts.com",
    "support": "COMMUNITY",
    "category": "Import-Export",
}

import bpy, bmesh
from mathutils import Vector
# ImportHelper is a helper class, defines filename and invoke() function which calls the file selector
from bpy_extras.io_utils import ImportHelper

import os
import sys
import math
import struct
from struct import calcsize, unpack


try:
    os.SEEK_SET
except AttributeError:
    os.SEEK_SET, os.SEEK_CUR, os.SEEK_END = range(3)


def read_string(fhandle, offset):
    fhandle.seek(offset, os.SEEK_SET)
    string = ''
    c = fhandle.read(1)
    while(c != b'' and c != b'\x00'):
        string += c.decode('ascii')
        c = fhandle.read(1)
    return string


def find_in_folder(folder, name):
    """Case insensitive file/folder search tool
    
    Parameters
    ==========
    
    folder : string
        Folder where the file should be looked for
    name : string
        Name of the file (case will be ignored)

    Returns
    =======

    filename : string
        The file name (case sensitive), None if the file cannot be found.
    """
    for filename in os.listdir(folder):
        if filename.lower() == name.lower():
            return filename


class s3o_header(object):
    binary_format = "<12sI5f4I"

    magic = 'Spring unit'  # char [12] "Spring unit\0"
    version = 0    # uint = 0
    radius = 0.0 # float: radius of collision sphere
    height = 0.0 # float: height of whole object
    midx = 0.0 # float offset from origin
    midy = 0.0 #
    midz = 0.0 #
    rootPieceOffset = 0 # offset of root piece
    collisionDataOffset = 0 # offset of collision data, 0 = no data
    texture1Offset = 0 # offset to filename of 1st texture
    texture2Offset = 0 # offset to filename of 2nd texture

    def load(self, fhandle):
        tmp_data = fhandle.read(struct.calcsize(self.binary_format))
        data = struct.unpack(self.binary_format, tmp_data)
        self.magic = data[0].decode('ascii').replace('\x00', '').strip()
        if(self.magic != 'Spring unit'):
            raise IOError("Not a Spring unit file: '" + self.magic + "'")
            return
        self.version = data[1]
        if(self.version != 0):
            raise ValueError('Wrong file version: ' + self.version)
            return
        self.radius = data[2]
        self.height = data[3]
        self.midx = -data[4]
        self.midy = data[5]
        self.midz = data[6]
        self.rootPieceOffset = data[7]
        self.collisionDataOffset = data[8]

        self.texture1Offset = data[9]
        if(self.texture1Offset == 0):
            self.texture1 = ''
        else:
            self.texture1 = read_string(fhandle, self.texture1Offset)

        self.texture2Offset = data[10]
        if(self.texture2Offset == 0):
            self.texture2 = ''
        else:
            self.texture2 = read_string(fhandle, self.texture2Offset)
        return


class s3o_piece(object):
    binary_format = "<10I3f"

    name = ''
    verts = []
    faces = []
    parent = '' 
    children = []

    nameOffset = 0 # uint
    numChildren = 0 # uint
    childrenOffset = 0 # uint
    numVerts = 0 # uint
    vertsOffset = 0 # uint
    vertType = 0 # uint
    primitiveType = 0 # 0 = tri, 1 = tristrips, 2 = quads
    vertTableSize = 0 # number of indexes in vert table
    vertTableOffset = 0
    collisionDataOffset = 0
    xoffset = 0.0
    yoffset = 0.0
    zoffset = 0.0

    def load(self, fhandle, offset, material):
        fhandle.seek(offset, os.SEEK_SET)
        tmp_data = fhandle.read(struct.calcsize(self.binary_format))
        data = struct.unpack(self.binary_format, tmp_data)

        self.nameOffset = data[0]
        self.numChildren = data[1]
        self.childrenOffset = data[2]
        self.numVerts = data[3]
        self.vertsOffset = data[4]
        self.vertType = data[5]
        self.primitiveType = data[6]
        self.vertTableSize = data[7]
        self.vertTableOffset = data[8]
        self.collisionDataOffset = data[9]
        self.xoffset = data[10]
        self.yoffset = data[11]
        self.zoffset = data[12]

        # load self
        # get name
        fhandle.seek(self.nameOffset, os.SEEK_SET)
        self.name = read_string(fhandle, self.nameOffset)

        # load verts
        self.verts = []
        for i in range(0, self.numVerts):
            vert = s3o_vert()
            vert.load(fhandle, self.vertsOffset + (i * struct.calcsize(vert.binary_format)))
            self.verts.append(vert)

        # load primitives
        fhandle.seek(self.vertTableOffset, os.SEEK_SET)
        self.faces = []
        if(self.primitiveType == 0): # triangles
            i = 0
            while(i < self.vertTableSize):
                tmp = fhandle.read(4 * 3)
                data = struct.unpack("<3I", tmp)
                face = [ int(data[0]), int(data[1]), int(data[2]) ]
                self.faces.append(face)
                i += 3
        elif(self.primitiveType == 1): # tristrips
            raise TypeError('Tristrips are unsupported so far')
        elif(self.primitiveType == 2): # quads
            i = 0
            while(i < self.vertTableSize):
                tmp = fhandle.read(4 * 4)
                data = struct.unpack("<4I", tmp)
                face = [ int(data[0]), int(data[1]), int(data[2]), int(data[3]) ]
                self.faces.append(face)
                i += 4
        else:
            raise TypeError('Unknown primitive type: ' + self.primitiveType)

        # if it has no verts or faces create an EMPTY instead
        if(self.numVerts == 0):
            bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 0, 0))
            self.ob = bpy.context.active_object
            self.ob.name = self.name
        else:
            bm = bmesh.new()
            tex = material.texture_slots[0]
            for v in self.verts:
                bm.verts.new((v.xpos, v.ypos, v.zpos))
                bm.verts.ensure_lookup_table()
                bm.verts[-1].normal = Vector((v.xnormal, v.ynormal, v.znormal))
            for f in self.faces:
                bm.faces.new([bm.verts[i] for i in f])
                bm.faces.ensure_lookup_table()
                uv_layer = bm.loops.layers.uv.verify()
                bm.faces.layers.tex.verify()
                for i, loop in enumerate(bm.faces[-1].loops):
                    uv = loop[uv_layer].uv
                    uv[0] = self.verts[f[i]].texu
                    uv[1] = self.verts[f[i]].texv
                    if tex is None or not tex.texture.image:
                        continue
                    ext = tex.texture.image.filepath[-4:]
                    if ext != '.dds' and ext != '.DDS':
                        uv[1] = 1.0 - uv[1]

            self.mesh = bpy.data.meshes.new(self.name)
            bm.to_mesh(self.mesh)
            self.ob = bpy.data.objects.new(self.name, self.mesh)
            bpy.context.scene.objects.link(self.ob)
            bpy.context.scene.update()
            bpy.context.scene.objects.active = self.ob
            bpy.ops.object.shade_smooth()

            matidx = len(self.ob.data.materials)
            self.ob.data.materials.append(material) 

            for face in self.mesh.polygons:
                face.material_index = matidx
    
        if(self.parent):
            self.ob.parent = self.parent.ob
        self.ob.location = [self.xoffset, self.yoffset, self.zoffset]
        self.ob.rotation_mode = 'ZXY'

        # load children
        if(self.numChildren > 0):
            # childrenOffset contains DWORDS containing offsets to child pieces
            fhandle.seek(self.childrenOffset, os.SEEK_SET)
            for i in range(0, self.numChildren):
                tmp = fhandle.read(4)
                offset = fhandle.tell()
                data = struct.unpack("<I", tmp)
                childOffset = data[0]
                child = s3o_piece()
                child.parent = self
                child.load(fhandle, childOffset, material)
                self.children.append(child)
                fhandle.seek(offset, os.SEEK_SET)
        return


class s3o_vert(object):
    binary_format = "<8f"
    xpos = 0.0
    ypos = 0.0
    zpos = 0.0
    xnormal = 0.0
    ynormal = 0.0
    znormal = 0.0
    texu = 0.0
    texv = 0.0

    def load(self, fhandle, offset):
        fhandle.seek(offset, os.SEEK_SET)
        tmp_data = fhandle.read(struct.calcsize(self.binary_format))
        data = struct.unpack(self.binary_format, tmp_data)

        self.xpos = data[0]
        self.ypos = data[1]
        self.zpos = data[2]
        self.xnormal = data[3]
        self.ynormal = data[4]
        self.znormal = data[5]
        self.texu = data[6]
        self.texv = data[7]


def load_s3o_file(s3o_filename, context, BATCH_LOAD=False):
    basename = os.path.basename(s3o_filename)
    objdir = os.path.dirname(s3o_filename)
    rootdir = objdir
    while os.path.basename(rootdir).lower() != "objects3d":
        rootdir = os.path.dirname(rootdir)
    rootdir = os.path.dirname(rootdir)
    texsdir = os.path.join(rootdir, find_in_folder(rootdir, 'unittextures'))

    fhandle = open(s3o_filename, "rb")

    header = s3o_header()
    header.load(fhandle)

    mat = bpy.data.materials.new(name=basename + '.mat')
    mat.diffuse_color = (1.0, 1.0, 1.0)
    mat.diffuse_shader = 'LAMBERT'
    mat.diffuse_intensity = 1.0
    mat.specular_color = (1.0, 1.0, 1.0)
    mat.specular_shader = 'COOKTORR'
    mat.specular_intensity = 0.5
    mat.ambient = 1.0
    mat.alpha = 1.0
    mat.emit = 0.0
    if(header.texture1):
        fname = find_in_folder(texsdir, header.texture1)
        image = bpy.data.images.load(os.path.join(texsdir, fname))
        tex = bpy.data.textures.new(basename + '.color', type='IMAGE')
        tex.image = image
        mtex = mat.texture_slots.add()
        mtex.texture = tex
        mtex.texture_coords = 'UV'
        mtex.uv_layer = 'UVMap'
        mtex.use_map_color_diffuse = True 
        mtex.diffuse_color_factor = 1.0
        mtex.mapping = 'FLAT'
    if(header.texture2):
        fname = find_in_folder(texsdir, header.texture2)
        image = bpy.data.images.load(os.path.join(texsdir, fname))
        tex = bpy.data.textures.new(basename + '.alpha', type='IMAGE')
        tex.image = image
        mtex = mat.texture_slots.add()
        mtex.texture = tex
        mtex.texture_coords = 'UV'
        mtex.uv_layer = 'UVMap'
        mtex.use_map_color_diffuse = False 
        mtex.use_map_specular = True
        mtex.specular_factor = 1.0
        mtex.mapping = 'FLAT'

    rootPiece = s3o_piece()
    rootPiece.load(fhandle, header.rootPieceOffset, mat)

    # create collision sphere
    bpy.ops.object.empty_add(type="SPHERE",
                             location=(header.midx, header.midz, header.midy),
                             radius=header.radius)
    bpy.context.active_object.name = basename + '.SpringRadius'
    bpy.ops.object.empty_add(type="ARROWS",
                             location=(header.midx, header.midz, header.midy),
                             radius=10.0)
    bpy.context.active_object.name = basename + '.SpringHeight'

    fhandle.close()
    return

class ImportS3O(bpy.types.Operator, ImportHelper):
    """Import a file in the Spring S3O format (.s3o)"""
    bl_idname = "import_scene.s3o"  # important since its how bpy.ops.import_scene.osm is constructed
    bl_label = "Import Spring S3O"
    bl_options = {"UNDO"}

    # ImportHelper mixin class uses this
    filename_ext = ".s3o"

    filter_glob = bpy.props.StringProperty(
        default="*.s3o",
        options={"HIDDEN"},
    )

    def execute(self, context):
        # setting active object if there is no active object
        if context.mode != "OBJECT":
            # if there is no object in the scene, only "OBJECT" mode is provided
            if not context.scene.objects.active:
                context.scene.objects.active = context.scene.objects[0]
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        
        load_s3o_file(self.filepath, context)
        
        bpy.ops.object.select_all(action="DESELECT")
        return {"FINISHED"}


# Only needed if you want to add into a dynamic menu
def menu_func_import(self, context):
    self.layout.operator(ImportS3O.bl_idname, text="Spring (.s3o)")

def register():
    bpy.utils.register_class(ImportS3O)
    bpy.types.INFO_MT_file_import.append(menu_func_import)

def unregister():
    bpy.utils.unregister_class(ImportS3O)
    bpy.types.INFO_MT_file_import.remove(menu_func_import)

# This allows you to run the script directly from blenders text editor
# to test the addon without having to install it.
if __name__ == "__main__":
    register()
